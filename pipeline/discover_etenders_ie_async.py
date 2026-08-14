from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/ireland"))
OUT.mkdir(parents=True, exist_ok=True)
PAGE_START = int(os.getenv("PAGE_START", "1"))
PAGE_END = int(os.getenv("PAGE_END", "50"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
CONCURRENCY = int(os.getenv("IE_PAGE_CONCURRENCY", "6"))
CHROME_BIN = os.getenv("CHROME_BIN", "").strip()
NOW = datetime.now(ZoneInfo("Europe/Dublin"))

TEXT_DATE_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(?:IST|GMT|UTC)\s+(\d{4})\b"
)
NUMERIC_DATETIME_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\b")
VALUE_AFTER_STATUS_RE = re.compile(
    r"Open\s+Tender\s+Submission\s+([0-9][0-9,]*(?:\.\d{1,2})?)\s+(?:\d+)?\s*$",
    re.I,
)


def clean(value: str) -> str:
    return " ".join((value or "").split())


def parse_deadline(text: str):
    # Current eTenders table format, e.g. 07/08/2026 21:25:26 11/09/2026 13:00:00.
    numeric = NUMERIC_DATETIME_RE.findall(text or "")
    if numeric:
        try:
            dt = datetime.strptime(numeric[-1], "%d/%m/%Y %H:%M:%S")
            return dt.replace(tzinfo=ZoneInfo("Europe/Dublin"))
        except ValueError:
            pass
    # Historical renderer fallback.
    hits = TEXT_DATE_RE.findall(text or "")
    if hits:
        mon, day, tm, year = hits[-1]
        try:
            dt = datetime.strptime(f"{mon} {day} {year} {tm}", "%b %d %Y %H:%M:%S")
            return dt.replace(tzinfo=ZoneInfo("Europe/Dublin"))
        except ValueError:
            pass
    return None


def infer_buyer(text: str, rid: str, title: str | None):
    # In the current table the buyer sits between resourceId and the first datetime.
    marker = str(rid)
    pos = text.find(marker)
    if pos < 0:
        return None
    tail = text[pos + len(marker) :].strip()
    m = NUMERIC_DATETIME_RE.search(tail)
    if not m:
        return None
    buyer = clean(tail[: m.start()])
    return buyer or None


def infer_value(text: str):
    m = VALUE_AFTER_STATUS_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_page_html(html: str, page_url: str, pg: int):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        text = clean(tr.get_text(" ", strip=True))
        if not text:
            continue
        rid = None
        title = None
        notice_url = None
        for a in tr.find_all("a", href=True):
            href = a.get("href") or ""
            m = re.search(r"resourceId=(\d+)", href)
            if m:
                rid = m.group(1)
                title = clean(a.get_text(" ", strip=True)) or title
                notice_url = urljoin(page_url, href)
                break
        if not rid:
            continue
        deadline = parse_deadline(text)
        buyer = infer_buyer(text, rid, title)
        estimated_value = infer_value(text)
        rows.append(
            {
                "candidate_id": f"IE:{rid}",
                "source": "IRELAND_ETENDERS",
                "portal": "IRELAND_ETENDERS",
                "resource_id": rid,
                "title": title or text[:240],
                "buyer": buyer,
                "deadline": deadline.isoformat() if deadline else None,
                "current": bool(deadline is None or deadline >= NOW),
                "notice_url": notice_url,
                "estimated_value": estimated_value,
                "currency": "EUR",
                "description": text,
                "route": {"resource_id": rid},
                "discovery_page": pg,
                "discovered_at": NOW.isoformat(),
            }
        )
    return rows


async def fetch_page(browser, sem: asyncio.Semaphore, pg: int):
    url = (
        "https://www.etenders.gov.ie/epps/quickSearchAction.do?"
        f"T01_ps={PAGE_SIZE}&d-3680175-n=1&d-3680175-o=1&"
        f"d-3680175-p={pg}&d-3680175-s=eppsId&searchType=cftFTS"
    )
    async with sem:
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            html = await page.content()
            return {"page": pg, "records": parse_page_html(html, page.url, pg), "error": None}
        except Exception as exc:
            return {"page": pg, "records": [], "error": repr(exc), "url": url}
        finally:
            await page.close()


async def main_async():
    sem = asyncio.Semaphore(CONCURRENCY)
    async with async_playwright() as p:
        launch_kwargs = {"headless": True}
        if CHROME_BIN and Path(CHROME_BIN).exists():
            launch_kwargs["executable_path"] = CHROME_BIN
        browser = await p.chromium.launch(**launch_kwargs)
        tasks = [fetch_page(browser, sem, pg) for pg in range(PAGE_START, PAGE_END + 1)]
        results = await asyncio.gather(*tasks)
        await browser.close()

    by_id = {}
    errors = []
    for result in results:
        if result.get("error"):
            errors.append({k: v for k, v in result.items() if k != "records"})
        for rec in result.get("records") or []:
            by_id.setdefault(rec["resource_id"], rec)

    records = list(by_id.values())
    records.sort(key=lambda r: (r.get("discovery_page", 9999), r.get("resource_id", "")))
    current = [r for r in records if r.get("current")]

    with (OUT / "raw.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with (OUT / "current.jsonl").open("w", encoding="utf-8") as f:
        for rec in current:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    stats = {
        "source": "IRELAND_ETENDERS",
        "page_start": PAGE_START,
        "page_end": PAGE_END,
        "page_concurrency": CONCURRENCY,
        "chrome_bin": CHROME_BIN or None,
        "raw_materialized": len(records),
        "current_materialized": len(current),
        "deadline_parsed": sum(1 for r in records if r.get("deadline")),
        "buyer_parsed": sum(1 for r in records if r.get("buyer")),
        "value_parsed": sum(1 for r in records if r.get("estimated_value") is not None),
        "page_errors": len(errors),
        "errors": errors,
        "generated_at": NOW.isoformat(),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main_async())
