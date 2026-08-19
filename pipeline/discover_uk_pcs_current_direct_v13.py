from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UK_PCS_OCDS_DIRECT"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://www.publiccontractsscotland.gov.uk/search/Search_MainPage.aspx"
NOW = datetime.now(timezone.utc)
PCS_TZ = ZoneInfo("Europe/London")
PAGE_TARGET = "ctl00$maincontent$PagingHelperTop$ddPageSelect"
PAGE_BOTTOM = "ctl00$maincontent$PagingHelperBottom$ddPageSelect"
HARD_MAX_PAGES = max(0, int(os.getenv("PCS_DIRECT_HARD_MAX_PAGES", "0")))
POST_TIMEOUT_MS = max(30000, int(os.getenv("PCS_DIRECT_POST_TIMEOUT_MS", "120000")))


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def parse_deadline(value: Any):
    text = clean(value)
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            local = datetime.strptime(text, fmt).replace(hour=23, minute=59, second=59, tzinfo=PCS_TZ)
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


def parse_rows(html: str, records: dict[str, dict[str, Any]]):
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

        # PCS reference is the notice-grain identity. OCID is retained separately
        # as procedure linkage so multiple notices under one procedure never
        # destructively overwrite one another.
        notice_identity = ref or ocid
        cid = f"UK-PCS:{notice_identity}"
        records[cid] = {
            "candidate_id": cid,
            "source": "UK_PCS_OCDS",
            "portal": "PUBLIC_CONTRACTS_SCOTLAND",
            "grain": "NOTICE_FIRST_TENDER",
            "reference": ref or None,
            "notice_id": ref or None,
            "ocid": ocid or None,
            "procedure_id": ocid or None,
            "title": title or text[:500],
            "buyer": clean(buyer_m.group(1) if buyer_m else "") or None,
            "country": "GB",
            "deadline": deadline.isoformat() if deadline else None,
            "current": True,
            "currentness_evidence": "PCS_CURRENT_OPPORTUNITIES_OFFICIAL_FILTER_STATE_CHAIN",
            "notice_type": notice_type,
            "notice_url": urljoin(URL, href) if href else URL,
            "description": text,
            "route": {"reference": ref or None, "ocid": ocid or None},
            "discovered_at": NOW.isoformat(),
        }
        parsed += 1
    return current_page, total_pages, total_reported, parsed


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def form_from_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if form is None:
        raise RuntimeError("PCS_DIRECT_FORM_MISSING_IN_RESPONSE")
    data: dict[str, Any] = {}
    for node in form.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if not name or node.has_attr("disabled"):
            continue
        tag = (node.name or "").lower()
        if tag == "input":
            typ = (node.get("type") or "text").lower()
            if typ in {"checkbox", "radio"} and not node.has_attr("checked"):
                continue
            data[name] = node.get("value") or ""
        elif tag == "select":
            selected = node.find_all("option", selected=True)
            if not selected:
                first = node.find("option")
                data[name] = (first.get("value") or "") if first else ""
            elif node.has_attr("multiple"):
                data[name] = [(x.get("value") or "") for x in selected]
            else:
                data[name] = selected[0].get("value") or ""
        else:
            data[name] = node.get_text() or ""
    return data


async def browser_form(page) -> dict[str, Any]:
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


async def select_current(page) -> tuple[str, str, str]:
    selects = page.locator("select")
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        options = await sel.evaluate(
            "el => Array.from(el.options||[], o => ({text:(o.textContent||'').trim(), value:o.value}))"
        )
        for option in options or []:
            text = clean(option.get("text"))
            if re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", text, re.I):
                value = str(option.get("value") or "")
                await sel.select_option(value=value)
                name = str(await sel.get_attribute("name") or "")
                if not name:
                    raise RuntimeError("PCS_CURRENT_FILTER_SELECT_HAS_NO_NAME")
                return name, value, text
    raise RuntimeError("PCS_CURRENT_OPPORTUNITY_FILTER_NOT_FOUND")


async def post_page(context, base_form, wanted: int, *, current_name: str, current_value: str):
    form = copy.deepcopy(base_form)
    form[current_name] = current_value
    form["__EVENTTARGET"] = PAGE_TARGET
    form["__EVENTARGUMENT"] = ""
    form[PAGE_TARGET] = str(wanted)
    if PAGE_BOTTOM in form:
        form[PAGE_BOTTOM] = str(wanted)
    response = await context.request.post(URL, form=form, timeout=POST_TIMEOUT_MS)
    text = await response.text()
    if response.status >= 400:
        raise RuntimeError(f"PCS POST returned HTTP {response.status}")
    return text, response.status


def persist(
    records,
    *,
    pages,
    total_pages,
    total_reported,
    source_rows_seen,
    errors,
    telemetry,
    exhausted,
    state_chain_bootstrap_proven,
):
    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", rows)
    count_match = bool(
        total_reported is not None
        and source_rows_seen >= total_reported
        and len(rows) >= total_reported
    )
    complete = bool(exhausted and state_chain_bootstrap_proven and not errors and count_match)
    stats = {
        "source": "UK_PCS_OCDS",
        "portal": "PUBLIC_CONTRACTS_SCOTLAND",
        "listing_contract": "PCS_CURRENT_OPPORTUNITIES_DIRECT_ASPNET_POST_V13_STATE_CHAIN",
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "source_rows_seen": source_rows_seen,
        "pages_fetched": pages,
        "total_pages": total_pages,
        "total_reported": total_reported,
        "state_chain_bootstrap_proven": state_chain_bootstrap_proven,
        "filtered_current_search_proven": state_chain_bootstrap_proven and bool(total_pages and total_reported),
        "direct_filtered_post_proven": state_chain_bootstrap_proven and bool(total_pages and total_reported),
        "count_matches_official_total": count_match,
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": bool(rows),
        "live_coverage_credit_allowed": complete and bool(rows),
        "errors": errors,
        "warnings": [],
        "telemetry": telemetry,
        "generated_at": NOW.isoformat(),
        "source_url": URL,
        "semantics": "Official PCS Current Opportunity registry. The initial all-notices WebForms state is forced into the filtered pager through a page-2 transition, then its returned ViewState/EventValidation is chained back to filtered page 1. Every subsequent filtered page is traversed sequentially with refreshed server state. Coverage credit requires stable page/total markers, complete page exhaustion, source-row and unique notice-reference reconciliation against the official total, and zero errors. Notice reference is the notice-grain identity; OCID is procedure linkage.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


async def main():
    records: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    telemetry: dict[str, Any] = {"url": URL, "pages": []}
    pages_fetched = 0
    source_rows_seen = 0
    total_pages = None
    total_reported = None
    exhausted = False
    state_chain_bootstrap_proven = False

    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            try:
                landing = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
                telemetry["landing_status"] = landing.status if landing else None
                current_name, current_value, current_text = await select_current(page)
                telemetry["filter"] = {"name": current_name, "value": current_value, "text": current_text}
                initial_state = await browser_form(page)
                initial_state[current_name] = current_value

                # PCS does not apply the Current Opportunity filter when the initial
                # all-notices state simply posts page 1. Moving to page 2 forces the
                # filtered pager. Its returned state can then safely navigate back
                # to page 1, establishing a fully filtered starting point.
                bootstrap_html, bootstrap_status = await post_page(
                    context,
                    initial_state,
                    2,
                    current_name=current_name,
                    current_value=current_value,
                )
                bpage, btotal_pages, btotal_reported, _ = page_markers(bootstrap_html)
                telemetry["bootstrap_page2"] = {
                    "status": bootstrap_status,
                    "page": bpage,
                    "total_pages": btotal_pages,
                    "total_reported": btotal_reported,
                }
                if bpage != 2 or not btotal_pages or not btotal_reported:
                    raise RuntimeError(
                        f"PCS filtered bootstrap page2 invalid: page={bpage} total_pages={btotal_pages} total={btotal_reported}"
                    )
                filtered_state = form_from_html(bootstrap_html)

                page1_html, status1 = await post_page(
                    context,
                    filtered_state,
                    1,
                    current_name=current_name,
                    current_value=current_value,
                )
                p1, tp, tr, parsed = parse_rows(page1_html, records)
                if p1 != 1 or tp != btotal_pages or tr != btotal_reported:
                    raise RuntimeError(
                        f"PCS filtered state-chain page1 mismatch: page={p1} pages={tp}/{btotal_pages} total={tr}/{btotal_reported}"
                    )
                total_pages, total_reported = tp, tr
                pages_fetched = 1
                source_rows_seen = parsed
                state_chain_bootstrap_proven = True
                telemetry["pages"].append({
                    "requested": 1,
                    "page": p1,
                    "total_pages": tp,
                    "total_reported": tr,
                    "rows_parsed": parsed,
                    "status": status1,
                })
                persist(
                    records,
                    pages=pages_fetched,
                    total_pages=total_pages,
                    total_reported=total_reported,
                    source_rows_seen=source_rows_seen,
                    errors=errors,
                    telemetry=telemetry,
                    exhausted=False,
                    state_chain_bootstrap_proven=state_chain_bootstrap_proven,
                )

                state = form_from_html(page1_html)
                last_page = total_pages if not HARD_MAX_PAGES else min(total_pages, HARD_MAX_PAGES)
                for wanted in range(2, last_page + 1):
                    html, status = await post_page(
                        context,
                        state,
                        wanted,
                        current_name=current_name,
                        current_value=current_value,
                    )
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
                    telemetry["pages"].append({
                        "requested": wanted,
                        "page": page_no,
                        "total_pages": tp2,
                        "total_reported": tr2,
                        "rows_parsed": parsed,
                        "status": status,
                    })
                    state = form_from_html(html)
                    persist(
                        records,
                        pages=pages_fetched,
                        total_pages=total_pages,
                        total_reported=total_reported,
                        source_rows_seen=source_rows_seen,
                        errors=errors,
                        telemetry=telemetry,
                        exhausted=False,
                        state_chain_bootstrap_proven=state_chain_bootstrap_proven,
                    )

                if HARD_MAX_PAGES and total_pages and HARD_MAX_PAGES < total_pages:
                    errors.append({
                        "type": "HARD_PAGE_CAP_REACHED",
                        "max_pages": HARD_MAX_PAGES,
                        "total_pages": total_pages,
                    })
                elif not errors and total_pages and pages_fetched == total_pages:
                    exhausted = True
            finally:
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
        state_chain_bootstrap_proven=state_chain_bootstrap_proven,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
