from __future__ import annotations

import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/IT_ANAC_DELTA"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://pubblicitalegale.anticorruzione.it/ricerca-generica"
BASE = "https://pubblicitalegale.anticorruzione.it"
NOW = datetime.now(timezone.utc)
LOOKBACK_DAYS = max(90, int(os.getenv("ANAC_PVL_LOOKBACK_DAYS", "730")))
MAX_PAGES = max(1, int(os.getenv("ANAC_PVL_MAX_PAGES", "1200")))
WAIT_MS = max(500, int(os.getenv("ANAC_PVL_WAIT_MS", "1200")))
DETAIL_WORKERS = max(1, min(12, int(os.getenv("ANAC_PVL_DETAIL_WORKERS", "8"))))
UA = "Tender-Engine/6.4 (+public procurement research; ANAC PVL public service)"
S = requests.Session(); S.headers.update({"User-Agent": UA, "Accept": "text/html,application/json,*/*"})
UUID_RE = re.compile(r"/(?:bandi|avvisi)/([0-9a-f-]{36})(?:\b|/|\?)", re.I)
DATE_PATTERNS = [
    re.compile(r"(?:termine\s+(?:per\s+)?(?:la\s+)?presentazione\s+(?:delle\s+)?offerte|termine\s+ricevimento\s+offerte|data\s+scadenza|scadenza)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/20\d{2})(?:\s+(?:ore\s*)?(\d{1,2}[:.]\d{2}))?", re.I),
    re.compile(r"(?:deadline|closing\s+date)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})", re.I),
]


def clean(v): return " ".join(str(v or "").split())

def parse_dt(value):
    text = clean(value).replace(".", ":")
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError: pass
    return None

def first_deadline(text):
    for pattern in DATE_PATTERNS:
        m = pattern.search(text or "")
        if not m: continue
        raw = m.group(1)
        if len(m.groups()) > 1 and m.group(2): raw += " " + m.group(2).replace(".", ":")
        dt = parse_dt(raw)
        if dt: return dt
    return None

def parse_money(text):
    for label in ("Valore complessivo stimato", "Importo lotto", "Importo", "Valore stimato"):
        m = re.search(re.escape(label) + r"[^\d]{0,40}([\d.]+(?:,\d{1,2})?)\s*€", text, re.I)
        if m:
            try: return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError: pass
    return None

def fetch_detail(item):
    notice_id, url, fallback_title, published = item
    try:
        r = S.get(url, timeout=45); r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        title = fallback_title
        h = soup.find(["h1", "h2", "h3", "h4"])
        if h and len(clean(h.get_text(" ", strip=True))) > 8: title = clean(h.get_text(" ", strip=True))
        deadline = first_deadline(text)
        buyer = None
        bm = re.search(r"Denominazione\s+S\.A\./E\.C\.\s+(.+?)(?:Codice\s+Fiscale|Sezione|SEZIONE)", text, re.I)
        if bm: buyer = clean(bm.group(1))[:800]
        cpvs = []
        for code in re.findall(r"\b\d{8}(?:-\d)?\b", text):
            if code not in cpvs: cpvs.append(code)
        desc = None
        dm = re.search(r"Descrizione\s+(.+?)(?:Valore\s+complessivo|Importo|Luogo\s+principale|Sezione|SEZIONE)", text, re.I)
        if dm: desc = clean(dm.group(1))[:8000]
        return {"notice_id": notice_id, "title": title, "buyer": buyer, "deadline": deadline, "estimated_value": parse_money(text), "cpv": cpvs[:20], "description": desc or text[:10000], "published": published, "notice_url": url, "error": None}
    except Exception as exc:
        return {"notice_id": notice_id, "title": fallback_title, "buyer": None, "deadline": None, "estimated_value": None, "cpv": [], "description": "", "published": published, "notice_url": url, "error": repr(exc)}

def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as fh:
        for row in rows: fh.write(json.dumps(row, ensure_ascii=False) + "\n")

async def choose_option_containing(page, phrase):
    selects = page.locator("select")
    for i in range(await selects.count()):
        sel = selects.nth(i); opts = sel.locator("option")
        for j in range(await opts.count()):
            opt = opts.nth(j); text = clean(await opt.inner_text())
            if phrase.lower() in text.lower():
                value = await opt.get_attribute("value")
                await sel.select_option(value=value) if value is not None else await sel.select_option(label=text)
                return True
    # Angular/material style fallback.
    try:
        trigger = page.get_by_text(re.compile(r"Tipologie\s+avvisi", re.I)).first
        await trigger.click(timeout=4000); await page.wait_for_timeout(300)
        option = page.get_by_text(re.compile(phrase, re.I)).last
        await option.click(timeout=4000); return True
    except Exception:
        return False

async def fill_date_near(page, label_pattern, value):
    labels = page.get_by_text(re.compile(label_pattern, re.I))
    for i in range(min(await labels.count(), 10)):
        label = labels.nth(i)
        for up in range(1, 6):
            try:
                loc = label.locator("xpath=" + "/.." * up).locator("input")
                if await loc.count():
                    await loc.first.fill(value); return True
            except Exception: pass
    return False

async def submit_search(page):
    for loc in (page.get_by_role("button", name=re.compile(r"^Cerca$", re.I)), page.locator("button").filter(has_text=re.compile(r"Cerca", re.I))):
        try:
            if await loc.count():
                await loc.first.click(timeout=8000); await page.wait_for_timeout(WAIT_MS); return True
        except Exception: pass
    return False

async def next_page(page):
    for loc in (page.locator("a[rel=next]"), page.locator("button[aria-label*='next' i],a[aria-label*='next' i]"), page.get_by_role("button", name=re.compile(r"next|successiv|›|»", re.I)), page.get_by_role("link", name=re.compile(r"next|successiv|›|»", re.I))):
        try:
            for i in range(min(await loc.count(), 8)):
                node = loc.nth(i); cls = clean(await node.get_attribute("class")).lower(); aria = clean(await node.get_attribute("aria-disabled")).lower()
                if "disabled" in cls or aria == "true": continue
                await node.click(timeout=6000); await page.wait_for_timeout(WAIT_MS); return True
        except Exception: pass
    return False

async def main():
    links = {}; errors = []; warnings = []; pages = 0; exhausted = False; telemetry = {"url": URL, "lookback_days": LOOKBACK_DAYS}
    start_date = (NOW - timedelta(days=LOOKBACK_DAYS)).strftime("%d/%m/%Y")
    end_date = NOW.strftime("%d/%m/%Y")
    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            page = await browser.new_page(viewport={"width": 1440, "height": 1100}, user_agent=UA)
            r = await page.goto(URL, wait_until="domcontentloaded", timeout=90000); telemetry["http_status"] = r.status if r else None
            await page.wait_for_timeout(WAIT_MS)
            type_ok = await choose_option_containing(page, "Bandi e avvisi di indizione")
            # Select the first non-placeholder native value for required search type if present.
            selects = page.locator("select")
            for i in range(await selects.count()):
                sel = selects.nth(i); opts = sel.locator("option"); texts = [clean(await opts.nth(j).inner_text()) for j in range(await opts.count())]
                if any("tipologia ricerca" in t.lower() for t in texts):
                    continue
            date_from_ok = await fill_date_near(page, r"Data\s+di\s+pubblicazione\s*\(da\)", start_date)
            date_to_ok = await fill_date_near(page, r"Data\s+di\s+pubblicazione\s*\(a\)", end_date)
            telemetry.update({"type_filter_set": type_ok, "date_from_set": date_from_ok, "date_to_set": date_to_ok})
            if not type_ok:
                errors.append({"type": "PVL_TENDER_TYPE_FILTER_NOT_FOUND"})
            else:
                await submit_search(page)
                try: await page.locator("a[href*='/bandi/']").first.wait_for(timeout=30000)
                except Exception: errors.append({"type": "PVL_RESULT_LINKS_NOT_MATERIALIZED"})
            seen = set()
            for _ in range(MAX_PAGES):
                if errors: break
                found = []
                loc = page.locator("a[href*='/bandi/']")
                for i in range(await loc.count()):
                    a = loc.nth(i); href = clean(await a.get_attribute("href")); m = UUID_RE.search(href)
                    if not m: continue
                    nid = m.group(1).lower(); title = clean(await a.inner_text())
                    found.append(nid); links[nid] = (urljoin(BASE, href), title)
                sig = tuple(sorted(set(found)))
                if not sig: break
                if sig in seen: errors.append({"type": "PVL_PAGINATION_REPEATED_RESULT_SET", "page": pages + 1}); break
                seen.add(sig); pages += 1
                if not await next_page(page): exhausted = True; break
            else: errors.append({"type": "PVL_HARD_PAGE_CAP_REACHED", "max_pages": MAX_PAGES})
            await browser.close()
    except Exception as exc:
        errors.append({"type": "PVL_BROWSER_ERROR", "error": repr(exc)})

    details = []
    if links:
        items = [(nid, url, title, None) for nid, (url, title) in links.items()]
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            futures = [pool.submit(fetch_detail, item) for item in items]
            for future in as_completed(futures): details.append(future.result())
    rows = []
    detail_errors = 0
    for d in details:
        if d.get("error"): detail_errors += 1
        deadline = d.get("deadline")
        if deadline and deadline < NOW: continue
        nid = d["notice_id"]
        rows.append({"candidate_id": f"IT-PVL:{nid}", "source": "IT_ANAC_PVL", "portal": "ANAC_PVL", "notice_id": nid, "title": d.get("title") or nid, "buyer": d.get("buyer"), "country": "IT", "deadline": deadline.isoformat() if deadline else None, "current": True, "currentness_evidence": "ANAC_PVL_FUTURE_DEADLINE" if deadline else "ANAC_PVL_RECENT_COMPETITION_NOTICE_DEADLINE_UNKNOWN", "notice_url": d.get("notice_url"), "description": d.get("description") or "", "cpv": d.get("cpv") or [], "estimated_value": d.get("estimated_value"), "currency": "EUR", "route": {"pvl_notice_id": nid}, "discovered_at": NOW.isoformat()})
    rows.sort(key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows); write_jsonl(OUT / "current.jsonl", rows)
    # The search itself may be fully paged, but it reconstructs live state from a
    # conservative publication window. Do not turn that into a false exhaustive-current claim.
    stats = {"source": "IT_ANAC_PVL", "portal": "ANAC_PVL", "listing_contract": "ANAC_PVL_PUBLIC_TENDER_WINDOW_V1", "raw_materialized": len(rows), "current_materialized": len(rows), "search_pages_fetched": pages, "search_pagination_exhausted": exhausted, "detail_errors": detail_errors, "publication_lookback_days": LOOKBACK_DAYS, "enumeration_exhausted": False, "enumeration_complete": False, "live_candidate_capable": True, "live_coverage_credit_allowed": False, "errors": errors, "warnings": warnings + [{"type": "BOUNDED_PUBLICATION_WINDOW_NOT_FULL_CURRENT_UNIVERSE", "lookback_days": LOOKBACK_DAYS}], "generated_at": NOW.isoformat(), "source_url": URL}
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not rows: raise SystemExit(3)

if __name__ == "__main__": asyncio.run(main())
