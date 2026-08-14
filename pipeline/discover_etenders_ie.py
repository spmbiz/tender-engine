from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/ireland"))
OUT.mkdir(parents=True, exist_ok=True)
PAGE_START = int(os.getenv("PAGE_START", "1"))
PAGE_END = int(os.getenv("PAGE_END", str(PAGE_START + 9)))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
NOW = datetime.now(ZoneInfo("Europe/Dublin"))

DATE_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(?:IST|GMT|UTC)\s+(\d{4})\b"
)


def parse_deadline(text: str):
    hits = DATE_RE.findall(text or "")
    if not hits:
        return None
    mon, day, tm, year = hits[-1]
    try:
        dt = datetime.strptime(f"{mon} {day} {year} {tm}", "%b %d %Y %H:%M:%S")
        return dt.replace(tzinfo=ZoneInfo("Europe/Dublin"))
    except ValueError:
        return None


def clean(s: str) -> str:
    return " ".join((s or "").split())


records: list[dict] = []
errors: list[dict] = []
seen: set[str] = set()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    for pg in range(PAGE_START, PAGE_END + 1):
        url = (
            "https://www.etenders.gov.ie/epps/quickSearchAction.do?"
            f"T01_ps={PAGE_SIZE}&d-3680175-n=1&d-3680175-o=1&"
            f"d-3680175-p={pg}&d-3680175-s=eppsId&searchType=cftFTS"
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(250)
            rows = page.locator("tr")
            for i in range(rows.count()):
                tr = rows.nth(i)
                try:
                    text = clean(tr.inner_text())
                except Exception:
                    continue
                if not text:
                    continue
                rid = None
                title = None
                notice_url = None
                links = tr.locator("a[href]")
                for j in range(links.count()):
                    try:
                        a = links.nth(j)
                        href = a.get_attribute("href") or ""
                        m = re.search(r"resourceId=(\d+)", href)
                        if m:
                            rid = m.group(1)
                            title = clean(a.inner_text()) or title
                            notice_url = urljoin(page.url, href)
                            break
                    except Exception:
                        pass
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                deadline = parse_deadline(text)
                records.append(
                    {
                        "candidate_id": f"IE:{rid}",
                        "source": "IRELAND_ETENDERS",
                        "portal": "IRELAND_ETENDERS",
                        "resource_id": rid,
                        "title": title or text[:240],
                        "buyer": None,
                        "deadline": deadline.isoformat() if deadline else None,
                        "current": bool(deadline is None or deadline >= NOW),
                        "notice_url": notice_url,
                        "estimated_value": None,
                        "currency": "EUR",
                        "description": text,
                        "route": {"resource_id": rid},
                        "discovery_page": pg,
                        "discovered_at": NOW.isoformat(),
                    }
                )
        except Exception as exc:
            errors.append({"page": pg, "url": url, "error": repr(exc)})
    browser.close()

# Keep every materially enumerated identity in raw; current is a convenience subset.
raw_path = OUT / f"raw_{PAGE_START}_{PAGE_END}.jsonl"
with raw_path.open("w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

current = [r for r in records if r.get("current")]
cur_path = OUT / f"current_{PAGE_START}_{PAGE_END}.jsonl"
with cur_path.open("w", encoding="utf-8") as f:
    for rec in current:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

stats = {
    "source": "IRELAND_ETENDERS",
    "page_start": PAGE_START,
    "page_end": PAGE_END,
    "raw_materialized": len(records),
    "current_materialized": len(current),
    "errors": errors,
    "generated_at": NOW.isoformat(),
}
(OUT / f"stats_{PAGE_START}_{PAGE_END}.json").write_text(
    json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(stats, indent=2, ensure_ascii=False))
