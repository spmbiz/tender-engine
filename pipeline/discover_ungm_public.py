from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UNGM_PUBLIC"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://www.ungm.org/Public/Notice"
NOW = datetime.now(timezone.utc)
MAX_PAGES = max(1, int(os.getenv("UNGM_MAX_PAGES", "2000")))
WAIT_MS = max(500, int(os.getenv("UNGM_PAGE_WAIT_MS", "1200")))
NOTICE_RE = re.compile(r"/Public/Notice/(\d+)(?:\b|/|\?)", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}[-/][A-Za-z]{3}[-/]20\d{2}|\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})\b")
RESULT_WINDOW_RE = re.compile(r"Displaying\s+results\s+(\d+)\s+to\s+(\d+)\s+of\s+([\d,]+)", re.I)


def clean(value): return " ".join(str(value or "").split())

def parse_date(value):
    text = clean(value)
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception: pass
    return None

def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as fh:
        for row in rows: fh.write(json.dumps(row, ensure_ascii=False) + "\n")

def persist(records, *, pages, exhausted, total_reported, errors, warnings, telemetry):
    rows = sorted(records.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    current = [r for r in rows if r.get("current")]
    write_jsonl(OUT / "raw.jsonl", rows); write_jsonl(OUT / "current.jsonl", current)
    count_proof = total_reported is not None and len(current) >= int(total_reported)
    complete = bool(exhausted and not errors and current and (count_proof or telemetry.get("explicit_terminal_pager") is True))
    stats = {
        "source": "UNGM_PUBLIC", "portal": "UNGM", "listing_contract": "UNGM_PUBLIC_ACTIVE_OPPORTUNITIES_V2_EXHAUSTION_PROOF",
        "raw_materialized": len(rows), "current_materialized": len(current), "pages_fetched": pages,
        "total_reported": total_reported, "enumeration_exhausted": bool(exhausted), "enumeration_complete": complete,
        "live_candidate_capable": True, "live_coverage_credit_allowed": complete,
        "errors": errors, "warnings": warnings, "telemetry": telemetry, "generated_at": NOW.isoformat(), "source_url": URL,
        "semantics": "UNGM public Procurement Opportunities is read with Only currently active enabled. Coverage credit requires result-count or explicit terminal-pager proof; failure to locate a next control is never by itself exhaustion proof.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats

async def ensure_active_only(page, telemetry):
    labels = page.locator("label")
    for i in range(await labels.count()):
        label = labels.nth(i); text = clean(await label.inner_text())
        if "only currently active" not in text.lower(): continue
        try:
            target = await label.get_attribute("for")
            box = page.locator(f"#{target}") if target else label.locator("input[type=checkbox]")
            if await box.count() and not await box.first.is_checked(): await box.first.check()
            telemetry["active_filter_explicit"] = True; return
        except Exception: pass
    boxes = page.locator("input[type=checkbox]")
    for i in range(await boxes.count()):
        box = boxes.nth(i)
        try:
            parent_text = clean(await box.evaluate("el => el.parentElement ? el.parentElement.innerText : ''"))
            if "only currently active" in parent_text.lower():
                if not await box.is_checked(): await box.check()
                telemetry["active_filter_explicit"] = True; return
        except Exception: continue
    telemetry["active_filter_explicit"] = False
    telemetry["active_filter_contract"] = "UNGM_PUBLIC_DEFAULT_ACTIVE"

async def click_search(page):
    for loc in (page.get_by_role("button", name=re.compile(r"^search\s*$", re.I)), page.locator("input[type=submit][value*='Search' i]")):
        try:
            if await loc.count():
                await loc.first.click(timeout=8000); await page.wait_for_timeout(WAIT_MS); return True
        except Exception: continue
    return False

async def result_window(page):
    try: body = clean(await page.locator("body").inner_text())
    except Exception: return None
    m = RESULT_WINDOW_RE.search(body)
    if not m: return None
    return {"first": int(m.group(1)), "last": int(m.group(2)), "total": int(m.group(3).replace(",", ""))}

async def parse_page(page, records, telemetry):
    links = page.locator("a[href*='/Public/Notice/']"); found = 0; seen_on_page = set()
    for i in range(await links.count()):
        a = links.nth(i); href = clean(await a.get_attribute("href")); match = NOTICE_RE.search(href)
        if not match: continue
        notice_id = match.group(1)
        if notice_id in seen_on_page: continue
        seen_on_page.add(notice_id); title = clean(await a.inner_text())
        try:
            row = a.locator("xpath=ancestor::tr[1]")
            text = clean(await row.inner_text()) if await row.count() else clean(await a.evaluate("el => el.parentElement?.parentElement?.innerText || el.parentElement?.innerText || ''"))
            cells = []
            if await row.count():
                tds = row.locator("td"); cells = [clean(await tds.nth(j).inner_text()) for j in range(await tds.count())]
        except Exception: text, cells = title, []
        deadline = parse_date(cells[1]) if len(cells) >= 2 else None
        published = parse_date(cells[2]) if len(cells) >= 3 else None
        organization = cells[3] or None if len(cells) >= 4 else None
        opportunity_type = cells[4] or None if len(cells) >= 5 else None
        reference = cells[5] or None if len(cells) >= 6 else None
        country = cells[6] or None if len(cells) >= 7 else None
        if deadline is None:
            dm = re.search(r"Deadline(?:\s+on)?\s*:?\s*([^|]{6,40})", text, re.I)
            if dm:
                m = DATE_RE.search(dm.group(1)); deadline = parse_date(m.group(1)) if m else None
        current = not deadline or deadline >= NOW
        cid = f"UNGM:{notice_id}"
        records[cid] = {
            "candidate_id": cid, "source": "UNGM_PUBLIC", "portal": "UNGM", "notice_id": notice_id,
            "title": title or text[:500], "buyer": organization, "country": country,
            "deadline": deadline.isoformat() if deadline else None, "published": published.isoformat() if published else None,
            "current": current, "currentness_evidence": "UNGM_PUBLIC_ACTIVE_FILTER" if deadline is None else "UNGM_ACTIVE_FILTER_PLUS_DEADLINE",
            "notice_type": opportunity_type, "reference": reference, "notice_url": urljoin(URL, href), "description": text,
            "route": {"notice_id": notice_id}, "discovered_at": NOW.isoformat(),
        }; found += 1
    window = await result_window(page)
    telemetry.setdefault("pages", []).append({"page_index": len(telemetry.get("pages", [])) + 1, "rows_parsed": found, "result_window": window})
    return found, window

async def click_next(page, target_page):
    candidates = [
        page.locator("a[rel=next]"), page.locator("button[aria-label*='Next' i], a[aria-label*='Next' i]"),
        page.get_by_role("link", name=re.compile(r"^next$|^next\s|›|»", re.I)),
        page.get_by_role("button", name=re.compile(r"^next$|^next\s|›|»", re.I)),
        page.locator(".pagination a, .pager a, [class*='pagination' i] a, [class*='pager' i] a, [class*='paging' i] a").filter(has_text=re.compile(rf"^\s*(?:Page\s*)?{target_page}\s*$", re.I)),
    ]
    for loc in candidates:
        try: count = await loc.count()
        except Exception: continue
        for i in range(min(count, 20)):
            node = loc.nth(i)
            try:
                disabled = await node.get_attribute("disabled") is not None or (await node.get_attribute("aria-disabled")) == "true"
                classes = clean(await node.get_attribute("class")).lower()
                if disabled or "disabled" in classes: continue
                await node.click(timeout=8000); await page.wait_for_timeout(WAIT_MS); return True
            except Exception: continue
    return False

async def explicit_terminal_pager(page):
    # Terminal proof is allowed only when a next-like control exists and is
    # explicitly disabled. An absent control may simply be a selector we do not
    # understand, so absence is UNKNOWN rather than exhaustion.
    loc = page.locator("a[rel=next], button[aria-label*='Next' i], a[aria-label*='Next' i], .pagination .next, .pager .next, [class*='pagination' i] [class*='next' i]")
    try: count = await loc.count()
    except Exception: return False
    for i in range(min(count, 20)):
        node = loc.nth(i)
        try:
            aria = clean(await node.get_attribute("aria-disabled")).lower(); classes = clean(await node.get_attribute("class")).lower()
            if await node.get_attribute("disabled") is not None or aria == "true" or "disabled" in classes: return True
        except Exception: continue
    return False

async def main():
    records = {}; errors = []; warnings = []; telemetry = {"url": URL}; pages = 0; exhausted = False; total_reported = None
    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            response = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            telemetry["http_status"] = response.status if response else None
            if response and response.status >= 400: raise RuntimeError(f"UNGM public search returned HTTP {response.status}")
            await page.wait_for_timeout(WAIT_MS); await ensure_active_only(page, telemetry); await click_search(page)
            try: await page.locator("a[href*='/Public/Notice/']").first.wait_for(timeout=30000)
            except Exception:
                body = clean(await page.locator("body").inner_text())
                errors.append({"type": "PUBLIC_SEARCH_CAPTCHA_GATE" if "captcha" in body.lower() else "PUBLIC_RESULT_GRID_NOT_MATERIALIZED"})
            seen_signatures = set()
            for _ in range(MAX_PAGES):
                if errors: break
                ids = []
                loc = page.locator("a[href*='/Public/Notice/']")
                for i in range(await loc.count()):
                    href = clean(await loc.nth(i).get_attribute("href")); m = NOTICE_RE.search(href)
                    if m: ids.append(m.group(1))
                signature = tuple(sorted(set(ids)))
                if not signature: errors.append({"type": "ZERO_NOTICE_LINKS_ON_ACTIVE_RESULTS"}); break
                if signature in seen_signatures: errors.append({"type": "PAGINATION_REPEATED_RESULT_SET", "page": pages + 1}); break
                seen_signatures.add(signature)
                _, window = await parse_page(page, records, telemetry); pages += 1
                if window:
                    total_reported = window["total"]
                    if window["last"] >= window["total"] and len(records) >= window["total"]:
                        exhausted = True; telemetry["exhaustion_proof"] = "RESULT_WINDOW_COUNT"; break
                persist(records, pages=pages, exhausted=False, total_reported=total_reported, errors=errors, warnings=warnings, telemetry=telemetry)
                if await click_next(page, pages + 1): continue
                terminal = await explicit_terminal_pager(page)
                telemetry["explicit_terminal_pager"] = terminal
                if terminal and (total_reported is None or len(records) >= total_reported):
                    exhausted = True; telemetry["exhaustion_proof"] = "EXPLICIT_DISABLED_NEXT"; break
                errors.append({"type": "NO_EXHAUSTION_PROOF", "page": pages, "materialized": len(records), "total_reported": total_reported})
                break
            else: errors.append({"type": "HARD_PAGE_CAP_REACHED", "max_pages": MAX_PAGES})
            await browser.close()
    except Exception as exc: errors.append({"type": "UNGM_BROWSER_ERROR", "error": repr(exc)})
    if not records and not errors: errors.append({"type": "ZERO_ACTIVE_NOTICES"})
    stats = persist(records, pages=pages, exhausted=exhausted, total_reported=total_reported, errors=errors, warnings=warnings, telemetry=telemetry)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]: raise SystemExit(3)

if __name__ == "__main__": asyncio.run(main())
