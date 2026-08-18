from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UK_PCS_OCDS"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://www.publiccontractsscotland.gov.uk/search/Search_MainPage.aspx"
NOW = datetime.now(timezone.utc)
MAX_PAGES = max(1, int(os.getenv("PCS_CURRENT_MAX_PAGES", "2000")))
PAGE_WAIT_MS = max(300, int(os.getenv("PCS_CURRENT_PAGE_WAIT_MS", "900")))


def clean(value):
    return " ".join(str(value or "").split())


def parse_deadline(value):
    text = clean(value)
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def current_option(text: str) -> bool:
    # PCS currently renders the native option as singular "Current Opportunity",
    # while its help copy uses the plural "Current Opportunities". Match the
    # semantic root so a cosmetic singular/plural change cannot zero the lane.
    return bool(re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", clean(text), re.I))


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def persist(records, *, pages, total_reported, exhausted, errors, warnings, telemetry):
    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in rows if x.get("current")]
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)
    stats = {
        "source": "UK_PCS_OCDS",
        "portal": "PUBLIC_CONTRACTS_SCOTLAND",
        "listing_contract": "PCS_CURRENT_OPPORTUNITIES_BROWSER_V3",
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "pages_fetched": pages,
        "total_reported": total_reported,
        "enumeration_exhausted": bool(exhausted),
        "enumeration_complete": bool(exhausted and not errors and current),
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": bool(exhausted and not errors and current),
        "errors": errors,
        "warnings": warnings,
        "telemetry": telemetry,
        "generated_at": NOW.isoformat(),
        "source_url": URL,
        "semantics": "The official PCS Current Opportunity/Opportunities filter is used. Native and Telerik/custom Notice Type controls are supported. Only notices open for tender are traversed; coverage credit requires pagination exhaustion and a non-empty current set.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


async def select_current_opportunities(page, telemetry, errors):
    option_debug = []
    # 1) Native HTML select.
    selects = page.locator("select")
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        options = sel.locator("option")
        texts = []
        for oi in range(await options.count()):
            option = options.nth(oi)
            text = clean(await option.inner_text())
            if text:
                texts.append(text)
            if not current_option(text):
                continue
            value = await option.get_attribute("value")
            try:
                if value is not None:
                    await sel.select_option(value=value)
                else:
                    await sel.select_option(label=text)
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["current_filter_mode"] = "NATIVE_SELECT"
                telemetry["current_filter_option"] = text
                telemetry["current_filter_select_index"] = idx
                return True
            except Exception as exc:
                errors.append({"type": "CURRENT_FILTER_SELECT_ERROR", "mode": "NATIVE_SELECT", "error": repr(exc)})
                return False
        if texts:
            option_debug.append({"select_index": idx, "options": texts[:30]})

    # 2) PCS uses Telerik/custom controls on some renders. Find likely Notice
    # Type comboboxes, open them, then click the current-opportunity option.
    controls = page.locator(
        "[id*='NoticeType' i], [name*='NoticeType' i], [aria-label*='Notice Type' i], "
        "[title*='Notice Type' i], [role='combobox']"
    )
    control_debug = []
    for idx in range(min(await controls.count(), 40)):
        node = controls.nth(idx)
        try:
            visible = await node.is_visible()
        except Exception:
            visible = False
        try:
            meta = await node.evaluate("el => ({tag:el.tagName,id:el.id||'',name:el.getAttribute('name')||'',cls:el.className||'',aria:el.getAttribute('aria-label')||''})")
            control_debug.append(meta)
        except Exception:
            meta = {}
        if not visible:
            continue
        try:
            await node.click(timeout=2500)
        except Exception:
            try:
                parent = node.locator("xpath=ancestor-or-self::*[contains(@class,'RadComboBox')][1]")
                if await parent.count():
                    await parent.click(timeout=2500)
                else:
                    continue
            except Exception:
                continue
        await page.wait_for_timeout(300)
        popups = page.locator("li.rcbItem, li.rcbHovered, .rcbList li, [role='option']")
        for oi in range(min(await popups.count(), 200)):
            opt = popups.nth(oi)
            try:
                text = clean(await opt.inner_text())
                if current_option(text) and await opt.is_visible():
                    await opt.click(timeout=3000)
                    await page.wait_for_timeout(PAGE_WAIT_MS)
                    telemetry["current_filter_mode"] = "CUSTOM_COMBOBOX"
                    telemetry["current_filter_option"] = text
                    telemetry["current_filter_control"] = meta
                    return True
            except Exception:
                continue

    # 3) Exact visible option fallback. Avoid the help sentence containing the
    # same words by requiring the whole element to be only the option label.
    exact = page.get_by_text(re.compile(r"^\s*Current\s+Opportunit(?:y|ies)\s*$", re.I))
    for i in range(min(await exact.count(), 20)):
        candidate = exact.nth(i)
        try:
            if not await candidate.is_visible():
                continue
            await candidate.click(timeout=3000)
            await page.wait_for_timeout(PAGE_WAIT_MS)
            telemetry["current_filter_mode"] = "VISIBLE_EXACT_TEXT"
            telemetry["current_filter_option"] = clean(await candidate.inner_text())
            return True
        except Exception:
            continue

    telemetry["select_options_debug"] = option_debug
    telemetry["notice_type_controls_debug"] = control_debug[:40]
    errors.append({"type": "CURRENT_FILTER_NOT_FOUND", "native_selects_seen": len(option_debug), "candidate_controls_seen": len(control_debug)})
    return False


async def submit_search(page, telemetry):
    candidates = [
        page.get_by_role("button", name=re.compile(r"^search$", re.I)),
        page.locator("input[type=submit]").filter(has=page.locator("xpath=.")),
    ]
    for loc in candidates:
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 20)):
            node = loc.nth(i)
            try:
                text = clean(await node.get_attribute("value") or await node.inner_text())
                if text and "search" not in text.lower() and loc is candidates[1]:
                    continue
                await node.click(timeout=5000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["search_submitted"] = True
                return True
            except Exception:
                continue
    telemetry["search_submitted"] = False
    return False


async def parse_current_page(page, records, telemetry):
    body = clean(await page.locator("body").inner_text())
    total_match = re.search(r"total\s+([\d,]+)\s+items", body, re.I)
    total_reported = int(total_match.group(1).replace(",", "")) if total_match else None
    page_match = re.search(r"Showing\s+page\s+(\d+)\s+of\s+(\d+)", body, re.I)
    current_page = int(page_match.group(1)) if page_match else None
    total_pages = int(page_match.group(2)) if page_match else None

    parsed = 0
    rows = page.locator("tr")
    for i in range(await rows.count()):
        tr = rows.nth(i)
        text = clean(await tr.inner_text())
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
        notice_type = clean(type_m.group(1) if type_m else "")
        if deadline and deadline < NOW:
            continue
        links = tr.locator("a[href]")
        title = ""
        href = ""
        best_len = -1
        for j in range(await links.count()):
            a = links.nth(j)
            candidate_title = clean(await a.inner_text())
            candidate_href = clean(await a.get_attribute("href"))
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
            "currentness_evidence": "PCS_CURRENT_OPPORTUNITIES_OFFICIAL_FILTER",
            "notice_type": notice_type or None,
            "notice_url": urljoin(URL, href) if href else URL,
            "description": text,
            "route": {"reference": ref or None, "ocid": ocid or None},
            "discovered_at": NOW.isoformat(),
        }
        parsed += 1
    telemetry.setdefault("pages", []).append({"page": current_page, "rows_parsed": parsed, "total_pages": total_pages})
    return current_page, total_pages, total_reported, parsed


async def find_page_select(page):
    selects = page.locator("select")
    best = None
    best_max = 0
    best_labels = {}
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        options = sel.locator("option")
        labels = {}
        for oi in range(min(await options.count(), 2500)):
            text = clean(await options.nth(oi).inner_text())
            match = re.fullmatch(r"(?:Page\s*)?(\d+)", text, re.I)
            if match:
                labels[int(match.group(1))] = text
        if len(labels) >= 2 and max(labels) > best_max:
            best = sel
            best_max = max(labels)
            best_labels = labels
    return best, best_max, best_labels


async def advance(page, next_page, before_signature):
    selector, _, labels = await find_page_select(page)
    if selector is not None:
        try:
            await selector.select_option(label=labels.get(next_page, f"Page {next_page}"))
            await page.wait_for_timeout(PAGE_WAIT_MS)
            # A successful select/postback is enough to continue. The main loop
            # verifies the actual result-row signature on the next iteration,
            # so an ineffective postback cannot silently count as progress.
            return True
        except Exception:
            pass
    for pattern in (r"^next$", r"next\s*>", r"^>$", r"^›$", r"^»$"):
        loc = page.get_by_role("link", name=re.compile(pattern, re.I))
        try:
            if await loc.count():
                await loc.first.click(timeout=5000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await page.wait_for_timeout(PAGE_WAIT_MS)
                return True
        except Exception:
            pass
    return False


async def main():
    records = {}
    errors = []
    warnings = []
    telemetry = {"url": URL}
    pages = 0
    total_reported = None
    exhausted = False
    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            response = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            telemetry["http_status"] = response.status if response else None
            if response and response.status >= 400:
                raise RuntimeError(f"PCS search returned HTTP {response.status}")
            await page.wait_for_timeout(PAGE_WAIT_MS)
            if not await select_current_opportunities(page, telemetry, errors):
                await browser.close()
                stats = persist(records, pages=pages, total_reported=total_reported, exhausted=False, errors=errors, warnings=warnings, telemetry=telemetry)
                print(json.dumps(stats, ensure_ascii=False, indent=2))
                raise SystemExit(3)
            await submit_search(page, telemetry)

            seen_signatures = set()
            for _ in range(MAX_PAGES):
                body_text = clean(await page.locator("body").inner_text())
                refs = tuple(re.findall(r"Reference\s*No:\s*([^\s]+)", body_text, re.I))
                signature = refs if refs else (body_text[-5000:],)
                if signature in seen_signatures:
                    warnings.append({"type": "REPEATED_PAGE_SIGNATURE", "page": pages + 1})
                    break
                seen_signatures.add(signature)
                current_page, total_pages, reported, parsed = await parse_current_page(page, records, telemetry)
                pages += 1
                if reported is not None:
                    total_reported = reported
                persist(records, pages=pages, total_reported=total_reported, exhausted=False, errors=errors, warnings=warnings, telemetry=telemetry)
                if total_pages and current_page and current_page >= total_pages:
                    exhausted = True
                    break
                if not total_pages and parsed == 0:
                    warnings.append({"type": "NO_RESULT_ROWS_ON_PAGE", "page": current_page or pages})
                    break
                target = (current_page or pages) + 1
                if not await advance(page, target, signature):
                    if not total_pages or total_pages <= pages:
                        exhausted = True
                    else:
                        errors.append({"type": "PAGINATION_ADVANCE_FAILED", "page": current_page or pages, "target": target, "total_pages": total_pages})
                    break
            else:
                errors.append({"type": "HARD_PAGE_CAP_REACHED", "max_pages": MAX_PAGES})
            await browser.close()
    except SystemExit:
        raise
    except Exception as exc:
        errors.append({"type": "PCS_BROWSER_ERROR", "error": repr(exc)})

    if not records and not errors:
        errors.append({"type": "ZERO_CURRENT_OPPORTUNITIES"})
    stats = persist(records, pages=pages, total_reported=total_reported, exhausted=exhausted, errors=errors, warnings=warnings, telemetry=telemetry)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
