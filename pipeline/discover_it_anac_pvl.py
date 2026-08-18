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
# /bandi is already the official PVL lane "Bandi e avvisi di indizione".
# Prefer it to the advanced-search Angular form: it removes a fragile UI filter
# while keeping the same authoritative publication source.
URL = "https://pubblicitalegale.anticorruzione.it/bandi"
BASE = "https://pubblicitalegale.anticorruzione.it"
NOW = datetime.now(timezone.utc)
LOOKBACK_DAYS = max(90, int(os.getenv("ANAC_PVL_LOOKBACK_DAYS", "730")))
MAX_PAGES = max(1, int(os.getenv("ANAC_PVL_MAX_PAGES", "1200")))
WAIT_MS = max(500, int(os.getenv("ANAC_PVL_WAIT_MS", "1200")))
DETAIL_WORKERS = max(1, min(12, int(os.getenv("ANAC_PVL_DETAIL_WORKERS", "8"))))
UA = "Tender-Engine/6.5 (+public procurement research; ANAC PVL public service)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "text/html,application/json,*/*"})
UUID_RE = re.compile(r"/bandi/([0-9a-f-]{36})(?:\b|/|\?)", re.I)
PUBLISHED_RE = re.compile(r"Pubblicato\s*:\s*(\d{1,2}/\d{1,2}/20\d{2})", re.I)
CARD_DEADLINE_RE = re.compile(r"Scadenza\s*:\s*(\d{1,2}/\d{1,2}/20\d{2})", re.I)
DATE_PATTERNS = [
    re.compile(r"(?:termine\s+(?:per\s+)?(?:la\s+)?presentazione\s+(?:delle\s+)?offerte|termine\s+ricevimento\s+offerte|data\s+scadenza|scadenza)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/20\d{2})(?:\s+(?:ore\s*)?(\d{1,2}[:.]\d{2}))?", re.I),
    re.compile(r"(?:deadline|closing\s+date)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})", re.I),
]


def clean(v):
    return " ".join(str(v or "").split())


def parse_dt(value):
    text = clean(value).replace(".", ":")
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def first_deadline(text):
    for pattern in DATE_PATTERNS:
        m = pattern.search(text or "")
        if not m:
            continue
        raw = m.group(1)
        if len(m.groups()) > 1 and m.group(2):
            raw += " " + m.group(2).replace(".", ":")
        dt = parse_dt(raw)
        if dt:
            return dt
    return None


def parse_money(text):
    for label in ("Valore complessivo stimato", "Importo lotto", "Importo", "Valore stimato"):
        m = re.search(re.escape(label) + r"[^\d]{0,40}([\d.]+(?:,\d{1,2})?)\s*€", text, re.I)
        if m:
            try:
                return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
    return None


def fetch_detail(item):
    notice_id, url, fallback_title, published, card_deadline, card_text = item
    try:
        r = S.get(url, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        title = fallback_title
        # PVL detail pages may start with navigation headings; choose the first
        # substantive heading rather than blindly taking h1.
        for h in soup.find_all(["h1", "h2", "h3", "h4"]):
            candidate = clean(h.get_text(" ", strip=True))
            if len(candidate) > 20 and candidate.lower() not in {"ultime pubblicazioni", "bandi e avvisi di indizione"}:
                title = candidate
                break
        deadline = first_deadline(text) or card_deadline
        buyer = None
        bm = re.search(r"Denominazione\s+S\.A\./E\.C\.\s+(.+?)(?:Codice\s+Fiscale|Sezione|SEZIONE)", text, re.I)
        if bm:
            buyer = clean(bm.group(1))[:800]
        cpvs = []
        for code in re.findall(r"\b\d{8}(?:-\d)?\b", text):
            if code not in cpvs:
                cpvs.append(code)
        desc = None
        dm = re.search(r"Descrizione\s+(.+?)(?:Valore\s+complessivo|Importo|Luogo\s+principale|Sezione|SEZIONE)", text, re.I)
        if dm:
            desc = clean(dm.group(1))[:8000]
        return {
            "notice_id": notice_id,
            "title": title,
            "buyer": buyer,
            "deadline": deadline,
            "estimated_value": parse_money(text),
            "cpv": cpvs[:20],
            "description": desc or text[:10000] or card_text,
            "published": published,
            "notice_url": url,
            "error": None,
        }
    except Exception as exc:
        return {
            "notice_id": notice_id,
            "title": fallback_title,
            "buyer": None,
            "deadline": card_deadline,
            "estimated_value": None,
            "cpv": [],
            "description": card_text,
            "published": published,
            "notice_url": url,
            "error": repr(exc),
        }


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


async def next_page(page):
    candidates = (
        page.locator("a[rel=next]"),
        page.locator("button[aria-label*='next' i],a[aria-label*='next' i]"),
        page.get_by_role("button", name=re.compile(r"next|successiv|›|»", re.I)),
        page.get_by_role("link", name=re.compile(r"next|successiv|›|»", re.I)),
    )
    for loc in candidates:
        try:
            for i in range(min(await loc.count(), 8)):
                node = loc.nth(i)
                cls = clean(await node.get_attribute("class")).lower()
                aria = clean(await node.get_attribute("aria-disabled")).lower()
                if "disabled" in cls or aria == "true":
                    continue
                await node.click(timeout=6000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await page.wait_for_timeout(WAIT_MS)
                return True
        except Exception:
            pass
    return False


async def card_context(a):
    # PVL cards are rendered as nested blocks. Walk upward until publication or
    # deadline labels appear; this provides title/date evidence even if detail
    # enrichment later fails.
    for up in range(1, 7):
        try:
            node = a.locator("xpath=" + "/.." * up)
            text = clean(await node.inner_text())
            if "Pubblicato:" in text or "Scadenza:" in text:
                return text[:12000]
        except Exception:
            pass
    try:
        return clean(await a.evaluate("el => el.parentElement?.innerText || ''"))[:12000]
    except Exception:
        return ""


async def main():
    links = {}
    errors = []
    warnings = []
    pages = 0
    exhausted = False
    cutoff_reached = False
    telemetry = {"url": URL, "lookback_days": LOOKBACK_DAYS, "listing": "BANDI_DIRECT"}
    cutoff = NOW - timedelta(days=LOOKBACK_DAYS)

    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            page = await browser.new_page(viewport={"width": 1440, "height": 1100}, user_agent=UA)
            response = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            telemetry["http_status"] = response.status if response else None
            if response and response.status >= 400:
                raise RuntimeError(f"ANAC PVL /bandi returned HTTP {response.status}")
            await page.wait_for_timeout(WAIT_MS)
            try:
                await page.locator("a[href*='/bandi/']").first.wait_for(timeout=30000)
            except Exception:
                errors.append({"type": "PVL_BANDI_LINKS_NOT_MATERIALIZED"})

            seen_signatures = set()
            for _ in range(MAX_PAGES):
                if errors:
                    break
                found = []
                oldest_published = None
                loc = page.locator("a[href*='/bandi/']")
                for i in range(await loc.count()):
                    a = loc.nth(i)
                    href = clean(await a.get_attribute("href"))
                    m = UUID_RE.search(href)
                    if not m:
                        continue
                    nid = m.group(1).lower()
                    text = await card_context(a)
                    title = clean(await a.inner_text())
                    # The visible anchor is often just "Dettagli"; use the card's
                    # substantive text as fallback title in that case.
                    if not title or title.lower() in {"dettagli", "details"}:
                        candidate_lines = [x.strip() for x in re.split(r"Pubblicato:|Scadenza:|Dettagli", text, flags=re.I) if len(clean(x)) > 20]
                        if candidate_lines:
                            title = clean(max(candidate_lines, key=len))[:1500]
                    pm = PUBLISHED_RE.search(text)
                    published = parse_dt(pm.group(1)) if pm else None
                    dm = CARD_DEADLINE_RE.search(text)
                    card_deadline = parse_dt(dm.group(1)) if dm else None
                    if published and (oldest_published is None or published < oldest_published):
                        oldest_published = published
                    found.append(nid)
                    links[nid] = (urljoin(BASE, href), title, published, card_deadline, text)

                signature = tuple(sorted(set(found)))
                if not signature:
                    if pages == 0:
                        errors.append({"type": "PVL_ZERO_BANDI_LINKS_ON_FIRST_PAGE"})
                    else:
                        exhausted = True
                    break
                if signature in seen_signatures:
                    errors.append({"type": "PVL_PAGINATION_REPEATED_RESULT_SET", "page": pages + 1})
                    break
                seen_signatures.add(signature)
                pages += 1
                if oldest_published and oldest_published < cutoff:
                    cutoff_reached = True
                    break
                if not await next_page(page):
                    exhausted = True
                    break
            else:
                errors.append({"type": "PVL_HARD_PAGE_CAP_REACHED", "max_pages": MAX_PAGES})
            await browser.close()
    except Exception as exc:
        errors.append({"type": "PVL_BROWSER_ERROR", "error": repr(exc)})

    details = []
    if links:
        items = [(nid, *values) for nid, values in links.items()]
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            futures = [pool.submit(fetch_detail, item) for item in items]
            for future in as_completed(futures):
                details.append(future.result())

    rows = []
    detail_errors = 0
    for d in details:
        if d.get("error"):
            detail_errors += 1
        deadline = d.get("deadline")
        if deadline and deadline < NOW:
            continue
        published = d.get("published")
        # If pagination ran beyond the configured recall horizon, do not retain
        # unknown-deadline records older than that horizon.
        if deadline is None and published and published < cutoff:
            continue
        nid = d["notice_id"]
        rows.append({
            "candidate_id": f"IT-PVL:{nid}",
            "source": "IT_ANAC_PVL",
            "portal": "ANAC_PVL",
            "notice_id": nid,
            "title": d.get("title") or nid,
            "buyer": d.get("buyer"),
            "country": "IT",
            "deadline": deadline.isoformat() if deadline else None,
            "published": published.isoformat() if published else None,
            "current": True,
            "currentness_evidence": "ANAC_PVL_FUTURE_DEADLINE" if deadline else "ANAC_PVL_RECENT_BANDO_DEADLINE_UNKNOWN",
            "notice_url": d.get("notice_url"),
            "description": d.get("description") or "",
            "cpv": d.get("cpv") or [],
            "estimated_value": d.get("estimated_value"),
            "currency": "EUR",
            "route": {"pvl_notice_id": nid},
            "discovered_at": NOW.isoformat(),
        })
    rows.sort(key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", rows)

    warnings.append({
        "type": "BOUNDED_PUBLICATION_WINDOW_NOT_FULL_CURRENT_UNIVERSE",
        "lookback_days": LOOKBACK_DAYS,
        "cutoff_reached": cutoff_reached,
    })
    stats = {
        "source": "IT_ANAC_PVL",
        "portal": "ANAC_PVL",
        "listing_contract": "ANAC_PVL_BANDI_DIRECT_WINDOW_V2",
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "search_pages_fetched": pages,
        "search_pagination_exhausted": exhausted,
        "cutoff_reached": cutoff_reached,
        "detail_errors": detail_errors,
        "publication_lookback_days": LOOKBACK_DAYS,
        "enumeration_exhausted": False,
        "enumeration_complete": False,
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": False,
        "errors": errors,
        "warnings": warnings,
        "generated_at": NOW.isoformat(),
        "source_url": URL,
        "semantics": "Direct official PVL /bandi listing repairs live recall without the fragile advanced-search UI. It remains publication-window reconstruction, so it never claims exhaustive current-universe coverage.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not rows:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
