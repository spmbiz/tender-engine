from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

from discover_uk_pcs_current_direct import (
    OUT,
    URL,
    PAGE_TARGET,
    HARD_MAX_PAGES,
    bootstrap_current_form,
    parse_rows,
    post_form,
)


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def persist(records, *, pages_fetched, total_pages, total_reported, source_rows_seen, errors, telemetry, exhausted):
    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", rows)
    count_match = bool(total_reported is not None and source_rows_seen >= total_reported and len(rows) >= total_reported)
    complete = bool(exhausted and not errors and count_match and telemetry.get("filtered_total_stable"))
    stats = {
        "source": "UK_PCS_OCDS",
        "portal": "PUBLIC_CONTRACTS_SCOTLAND",
        "listing_contract": "PCS_CURRENT_OPPORTUNITIES_DIRECT_ASPNET_POST_V13_PAGER_BOOTSTRAP",
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "source_rows_seen": source_rows_seen,
        "pages_fetched": pages_fetched,
        "total_pages": total_pages,
        "total_reported": total_reported,
        "filtered_current_search_proven": bool(telemetry.get("filtered_total_stable")),
        "direct_filtered_post_proven": bool(telemetry.get("filtered_total_stable")),
        "count_matches_official_total": count_match,
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": complete,
        "errors": errors,
        "warnings": [],
        "telemetry": telemetry,
        "source_url": URL,
        "semantics": (
            "PCS exposes a stale unfiltered result count immediately after the Current Opportunity control is changed. "
            "V13 therefore bootstraps the public ASP.NET form, uses the official pager postback itself to materialize "
            "filtered page 2, replays page 1 with the same selected Current Opportunity value, and only trusts the "
            "filtered universe when page 1 and page 2 agree on total pages and total items. It then enumerates every "
            "filtered page and reconciles unique candidates against the portal-reported total."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


async def main():
    records = {}
    errors = []
    telemetry = {"url": URL, "pages": [], "bootstrap_mode": "PAGER_2_THEN_1"}
    pages_fetched = 0
    source_rows_seen = 0
    total_pages = None
    total_reported = None
    exhausted = False

    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            landing = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            telemetry["landing_status"] = landing.status if landing else None
            base_form, filter_meta = await bootstrap_current_form(page)
            telemetry["filter"] = filter_meta
            telemetry["viewstate_len"] = len(str(base_form.get("__VIEWSTATE") or ""))
            telemetry["eventvalidation_len"] = len(str(base_form.get("__EVENTVALIDATION") or ""))

            # The Search control has been observed returning the stale all-notices universe (~14k).
            # The pager postback applies the selected Current Opportunity filter correctly. Materialize
            # page 2 first to force that server-side filtered state, then independently replay page 1.
            html2, status2 = await post_form(context, base_form, event_target=PAGE_TARGET, page_value=2)
            p2, tp2, tr2, parsed2 = parse_rows(html2, records)
            if p2 != 2 or not tp2 or not tr2:
                raise RuntimeError(f"PCS filtered pager bootstrap failed: page={p2} total_pages={tp2} total={tr2}")

            html1, status1 = await post_form(context, base_form, event_target=PAGE_TARGET, page_value=1)
            p1, tp1, tr1, parsed1 = parse_rows(html1, records)
            if p1 != 1 or tp1 != tp2 or tr1 != tr2:
                raise RuntimeError(
                    f"PCS filtered total unstable between pager bootstrap pages: "
                    f"p1={p1}/{tp1}/{tr1} p2={p2}/{tp2}/{tr2}"
                )

            total_pages, total_reported = tp1, tr1
            telemetry["filtered_total_stable"] = True
            telemetry["stale_search_universe_ignored"] = True
            telemetry["pages"].extend([
                {"requested": 1, "page": p1, "total_pages": tp1, "total_reported": tr1, "rows_parsed": parsed1, "status": status1},
                {"requested": 2, "page": p2, "total_pages": tp2, "total_reported": tr2, "rows_parsed": parsed2, "status": status2},
            ])
            pages_fetched = 2
            source_rows_seen = parsed1 + parsed2
            persist(records, pages_fetched=pages_fetched, total_pages=total_pages, total_reported=total_reported,
                    source_rows_seen=source_rows_seen, errors=errors, telemetry=telemetry, exhausted=False)

            last_page = total_pages if not HARD_MAX_PAGES else min(total_pages, HARD_MAX_PAGES)
            for wanted in range(3, last_page + 1):
                html, status = await post_form(context, base_form, event_target=PAGE_TARGET, page_value=wanted)
                page_no, tp, tr, parsed = parse_rows(html, records)
                if page_no != wanted or tp != total_pages or tr != total_reported:
                    errors.append({
                        "type": "PCS_FILTERED_PAGE_CONTRACT_MISMATCH",
                        "requested": wanted,
                        "observed_page": page_no,
                        "observed_total_pages": tp,
                        "expected_total_pages": total_pages,
                        "observed_total_reported": tr,
                        "expected_total_reported": total_reported,
                    })
                    break
                pages_fetched += 1
                source_rows_seen += parsed
                telemetry["pages"].append({
                    "requested": wanted, "page": page_no, "total_pages": tp,
                    "total_reported": tr, "rows_parsed": parsed, "status": status,
                })
                persist(records, pages_fetched=pages_fetched, total_pages=total_pages, total_reported=total_reported,
                        source_rows_seen=source_rows_seen, errors=errors, telemetry=telemetry, exhausted=False)

            if HARD_MAX_PAGES and total_pages and HARD_MAX_PAGES < total_pages:
                errors.append({"type": "HARD_PAGE_CAP_REACHED", "max_pages": HARD_MAX_PAGES, "total_pages": total_pages})
            elif not errors and total_pages and pages_fetched == total_pages:
                exhausted = True
            await browser.close()
    except Exception as exc:
        errors.append({"type": "PCS_V13_ADAPTER_ERROR", "error": repr(exc)})

    stats = persist(records, pages_fetched=pages_fetched, total_pages=total_pages, total_reported=total_reported,
                    source_rows_seen=source_rows_seen, errors=errors, telemetry=telemetry, exhausted=exhausted)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
