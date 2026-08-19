from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UK_PCS_OCDS"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://www.publiccontractsscotland.gov.uk/search/Search_MainPage.aspx"
NOW = datetime.now(timezone.utc)
PCS_TZ = ZoneInfo("Europe/London")
PAGE_TARGET = "ctl00$maincontent$PagingHelperTop$ddPageSelect"
PAGE_BOTTOM = "ctl00$maincontent$PagingHelperBottom$ddPageSelect"
NOTICE_TYPE = "ctl00$maincontent$ddDocType"
SEARCH_TARGET = "ctl00$maincontent$btnSearch"
HARD_MAX_PAGES = max(0, int(os.getenv("PCS_DIRECT_HARD_MAX_PAGES", "0")))
POST_TIMEOUT_MS = max(30000, int(os.getenv("PCS_DIRECT_POST_TIMEOUT_MS", "90000")))


def clean(value):
    return " ".join(str(value or "").split())


def parse_deadline(value):
    text = clean(value)
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            local = datetime.strptime(text, fmt).replace(
                hour=23, minute=59, second=59, tzinfo=PCS_TZ
            )
            return local.astimezone(timezone.utc)
        except Exception:
            pass
    return None


def page_markers(html: str):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    page_match = re.search(r"Showing\s+page\s+(\d+)\s+of\s+(\d+)", text, re.I)
    total_match = re.search(r"total\s+([\d,]+)\s+items", text, re.I)
    return (
        int(page_match.group(1)) if page_match else None,
        int(page_match.group(2)) if page_match else None,
        int(total_match.group(1).replace(",", "")) if total_match else None,
        soup,
    )


def parse_rows(html: str, records: dict):
    current_page, total_pages, total_reported, soup = page_markers(html)
    parsed = 0
    for tr in soup.find_all("tr"):
        text = clean(tr.get_text(" ", strip=True))
        if "Reference No:" not in text or "Notice Type:" not in text:
            continue
        ref_m = re.search(r"Reference\s*No:\s*([^\s]+)", text, re.I)
        ocid_m = re.search(r"OCID:\s*([^\s]+)", text, re.I)
        buyer_m = re.search(r"Published\s*By:\s*(.*?)\s+Deadline\s*Date:", text, re.I)
        deadline_m = re.search(r"Deadline\s*Date:\s*([^\s]+)?", text, re.I)
        type_m = re.search(r"Notice\s*Type:\s*(.+)$", text, re.I)
        ref = clean(ref_m.group(1) if ref_m else "")
        ocid = clean(ocid_m.group(1) if ocid_m else "")
        if not ref and not ocid:
            continue
        deadline = parse_deadline(deadline_m.group(1) if deadline_m and deadline_m.group(1) else "")
        notice_type = clean(type_m.group(1) if type_m else "") or None
        title = ""
        href = ""
        best_len = -1
        for a in tr.find_all("a", href=True):
            candidate_title = clean(a.get_text(" ", strip=True))
            candidate_href = clean(a.get("href"))
            if candidate_title and len(candidate_title) > best_len:
                title, href, best_len = candidate_title, candidate_href, len(candidate_title)
        title = re.sub(r"\s*\(Opens in new tab\)\s*$", "", title, flags=re.I)
        cid = f"UK-PCS:{ocid or ref}"
        records[cid] = {
            "candidate_id": cid,
            "source": "UK_PCS_OCDS",
            "portal": "PUBLIC_CONTRACTS_SCOTLAND",
            "reference": ref or None,
            "ocid": ocid or None,
            "title": title or text[:500],
            "buyer": clean(buyer_m.group(1) if buyer_m else "") or None,
            "country": "GB",
            "deadline": deadline.isoformat() if deadline else None,
            "current": True,
            "currentness_evidence": "PCS_CURRENT_OPPORTUNITIES_OFFICIAL_FILTER_DIRECT_POST",
            "notice_type": notice_type,
            "notice_url": urljoin(URL, href) if href else URL,
            "description": text,
            "route": {"reference": ref or None, "ocid": ocid or None},
            "discovered_at": NOW.isoformat(),
        }
        parsed += 1
    return current_page, total_pages, total_reported, parsed


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def persist(records, *, pages, total_pages, total_reported, source_rows_seen, errors, telemetry, exhausted):
    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", rows)
    count_match = bool(total_reported is not None and source_rows_seen >= total_reported and len(rows) >= total_reported)
    complete = bool(exhausted and not errors and count_match)
    stats = {
        "source": "UK_PCS_OCDS",
        "portal": "PUBLIC_CONTRACTS_SCOTLAND",
        "listing_contract": "PCS_CURRENT_OPPORTUNITIES_DIRECT_ASPNET_POST_V12",
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "source_rows_seen": source_rows_seen,
        "pages_fetched": pages,
        "total_pages": total_pages,
        "total_reported": total_reported,
        "filtered_current_search_proven": bool(total_pages and total_reported),
        "direct_filtered_post_proven": bool(total_pages and total_reported),
        "count_matches_official_total": count_match,
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": complete,
        "errors": errors,
        "warnings": [],
        "telemetry": telemetry,
        "generated_at": NOW.isoformat(),
        "source_url": URL,
        "semantics": "One public browser bootstrap establishes the PCS session/form. The official Current Opportunity filter and ASP.NET pager are then replayed through same-origin POSTs using the page's ViewState/EventValidation. Coverage credit requires every filtered page plus candidate count reconciliation against the portal's reported total.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


async def serialize_form(page):
    return await page.locator("#aspnetForm").evaluate("""form => {
      const data = {};
      for (const el of Array.from(form.elements || [])) {
        if (!el.name || el.disabled) continue;
        const tag = (el.tagName || '').toLowerCase();
        const type = (el.type || '').toLowerCase();
        if ((type === 'checkbox' || type === 'radio') && !el.checked) continue;
        if (tag === 'select' && el.multiple) data[el.name] = Array.from(el.selectedOptions || [], o => o.value);
        else data[el.name] = el.value ?? '';
      }
      return data;
    }""")


async def bootstrap_current_form(page):
    selects = page.locator("select")
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        options = await sel.evaluate("el => Array.from(el.options||[], o => ({text:(o.textContent||'').trim(), value:o.value}))")
        for option in options or []:
            if re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", clean(option.get("text")), re.I):
                await sel.select_option(value=str(option.get("value")))
                form = await serialize_form(page)
                if form.get(NOTICE_TYPE) != str(option.get("value")):
                    raise RuntimeError("PCS Current Opportunity select did not persist into public form")
                return form, {"select_index": idx, "option_text": option.get("text"), "option_value": option.get("value")}
    raise RuntimeError("PCS Current Opportunity filter not found")


async def post_form(context, base_form, *, event_target, page_value=None):
    form = copy.deepcopy(base_form)
    form["__EVENTTARGET"] = event_target
    form["__EVENTARGUMENT"] = ""
    if page_value is not None:
        form[PAGE_TARGET] = str(page_value)
    response = await context.request.post(URL, form=form, timeout=POST_TIMEOUT_MS)
    text = await response.text()
    if response.status >= 400:
        raise RuntimeError(f"PCS POST returned HTTP {response.status}")
    return text, response.status


async def main():
    records = {}
    errors = []
    telemetry = {"url": URL, "pages": []}
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

            # First POST the Search control to materialize the filtered page 1.
            page1_html, status = await post_form(context, base_form, event_target=SEARCH_TARGET)
            p1, tp, tr, parsed = parse_rows(page1_html, records)
            if p1 != 1 or not tp or not tr:
                raise RuntimeError(f"PCS filtered search did not materialize page 1 cleanly: page={p1} total_pages={tp} total={tr}")
            total_pages, total_reported = tp, tr
            pages_fetched += 1
            source_rows_seen += parsed
            telemetry["pages"].append({"requested": 1, "page": p1, "total_pages": tp, "total_reported": tr, "rows_parsed": parsed, "status": status})
            persist(records, pages=pages_fetched, total_pages=total_pages, total_reported=total_reported, source_rows_seen=source_rows_seen, errors=errors, telemetry=telemetry, exhausted=False)

            last_page = total_pages if not HARD_MAX_PAGES else min(total_pages, HARD_MAX_PAGES)
            for wanted in range(2, last_page + 1):
                html, status = await post_form(context, base_form, event_target=PAGE_TARGET, page_value=wanted)
                page_no, tp2, tr2, parsed = parse_rows(html, records)
                if page_no != wanted or tp2 != total_pages or tr2 != total_reported:
                    errors.append({
                        "type": "PCS_DIRECT_PAGE_CONTRACT_MISMATCH",
                        "requested": wanted,
                        "observed_page": page_no,
                        "observed_total_pages": tp2,
                        "expected_total_pages": total_pages,
                        "observed_total_reported": tr2,
                        "expected_total_reported": total_reported,
                    })
                    break
                pages_fetched += 1
                source_rows_seen += parsed
                telemetry["pages"].append({"requested": wanted, "page": page_no, "total_pages": tp2, "total_reported": tr2, "rows_parsed": parsed, "status": status})
                persist(records, pages=pages_fetched, total_pages=total_pages, total_reported=total_reported, source_rows_seen=source_rows_seen, errors=errors, telemetry=telemetry, exhausted=False)

            if HARD_MAX_PAGES and total_pages and HARD_MAX_PAGES < total_pages:
                errors.append({"type": "HARD_PAGE_CAP_REACHED", "max_pages": HARD_MAX_PAGES, "total_pages": total_pages})
            elif not errors and total_pages and pages_fetched == total_pages:
                exhausted = True
            await browser.close()
    except Exception as exc:
        errors.append({"type": "PCS_DIRECT_ADAPTER_ERROR", "error": repr(exc)})

    stats = persist(
        records,
        pages=pages_fetched,
        total_pages=total_pages,
        total_reported=total_reported,
        source_rows_seen=source_rows_seen,
        errors=errors,
        telemetry=telemetry,
        exhausted=exhausted,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
