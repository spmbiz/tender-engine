from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL = os.environ["EPPS_BASE_URL"].rstrip("/")
SOURCE = os.environ["EPPS_SOURCE"].strip().upper()
PREFIX = os.getenv("EPPS_ID_PREFIX", SOURCE).strip()
TZ = ZoneInfo(os.getenv("EPPS_TIMEZONE", "Europe/Brussels"))
OUT = Path(os.getenv("DISCOVERY_OUT", f"discovery/global/{SOURCE}"))
OUT.mkdir(parents=True, exist_ok=True)
PAGE_START = max(1, int(os.getenv("PAGE_START", "1")))
PAGE_END = max(PAGE_START, int(os.getenv("PAGE_END", "20")))
PAGE_SIZE = max(10, min(100, int(os.getenv("PAGE_SIZE", "100"))))
NOW = datetime.now(TZ)

S = requests.Session()
S.headers.update({
    "User-Agent": "Tender-Engine/6.0 (+public procurement research; public ePPS pages only)",
    "Accept": "text/html,application/xhtml+xml,*/*",
})

RESOURCE_RE = re.compile(r"resourceId=(\d+)", re.I)
TEXTUAL_DEADLINE_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+"
    r"(?:CET|CEST|EET|EEST|GMT|UTC|IST)\s+(\d{4})\b",
    re.I,
)
NUMERIC_DEADLINE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)\b")
EXPIRED_STATUS = re.compile(r"\b(?:awarded|archived|cancelled|canceled|closed|evaluation|completed|withdrawn|ακυρώθηκε|κατακυρώθηκε)\b", re.I)
LIVE_STATUS = re.compile(r"\b(?:tender submission|open|awaiting tender opening|submission|υποβολ|προσφορ)\b", re.I)


def clean(v: str | None) -> str:
    return " ".join(str(v or "").split())


def request(url: str):
    last = None
    for attempt in range(4):
        try:
            r = S.get(url, timeout=45, allow_redirects=True)
            last = r
            if r.status_code in (408, 425, 429) or r.status_code >= 500:
                if attempt < 3:
                    time.sleep(min(12, 2 ** attempt) + 0.25 * attempt)
                    continue
            r.raise_for_status()
            return r
        except Exception:
            if attempt == 3:
                raise
            time.sleep(min(8, 2 ** attempt))
    if last is not None:
        last.raise_for_status()
    raise RuntimeError(url)


def parse_deadline(text: str):
    hits = list(NUMERIC_DEADLINE_RE.finditer(text or ""))
    for m in reversed(hits):
        raw = f"{m.group(1)} {m.group(2)}"
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=TZ)
            except ValueError:
                pass
    hits = list(TEXTUAL_DEADLINE_RE.finditer(text or ""))
    if hits:
        m = hits[-1]
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(4)} {m.group(3)}",
                "%b %d %Y %H:%M:%S",
            ).replace(tzinfo=TZ)
        except ValueError:
            pass
    return None


def infer_cells(tr):
    return [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]


def parse_page(html: str, page_url: str, page_no: int):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        rid = None
        detail_url = None
        title = None
        for a in tr.find_all("a", href=True):
            href = a.get("href") or ""
            m = RESOURCE_RE.search(href)
            if not m:
                continue
            rid = m.group(1)
            detail_url = urljoin(page_url, href)
            title = clean(a.get_text(" ", strip=True)) or title
            break
        if not rid:
            # Some ePPS result rows expose resourceId only on image/action attributes.
            raw = str(tr)
            m = RESOURCE_RE.search(raw)
            if not m:
                continue
            rid = m.group(1)
            detail_url = f"{BASE_URL}/epps/cft/prepareViewCfTWS.do?resourceId={rid}"

        text = clean(tr.get_text(" ", strip=True))
        cells = infer_cells(tr)
        deadline = parse_deadline(text)
        if deadline and deadline < NOW:
            continue
        if EXPIRED_STATUS.search(text) and not LIVE_STATUS.search(text):
            continue

        # Common ePPS result layout: ordinal, title, CA unique id, authority, info,
        # deadline, procedure, status, notice, award date. Fall back to text safely.
        if not title and len(cells) >= 2:
            title = cells[1]
        ca_unique = cells[2] if len(cells) >= 3 else None
        buyer = cells[3] if len(cells) >= 4 else None
        procedure = cells[6] if len(cells) >= 7 else None
        status = cells[7] if len(cells) >= 8 else None
        rows.append({
            "candidate_id": f"{PREFIX}:{rid}",
            "source": SOURCE,
            "portal": SOURCE,
            "resource_id": rid,
            "notice_id": clean(ca_unique) or rid,
            "title": clean(title) or text[:300],
            "buyer": clean(buyer) or None,
            "deadline": deadline.isoformat() if deadline else None,
            "current": True,
            "notice_url": detail_url,
            "description": text,
            "procurement_method": clean(procedure) or None,
            "source_status": clean(status) or None,
            "currency": "EUR",
            "route": {
                "resource_id": rid,
                "base_url": BASE_URL,
                "detail_url": detail_url,
                "documents_url": f"{BASE_URL}/epps/cft/listContractDocuments.do?resourceId={rid}",
            },
            "discovery_page": page_no,
            "discovered_at": NOW.isoformat(),
        })
    return rows


def page_url(pg: int) -> str:
    # searchSelect=5 is the public registry search used by ePPS installations.
    # It avoids submitting CAPTCHA forms; we only consume already-public result pages.
    return (
        f"{BASE_URL}/epps/quickSearchAction.do?T01_ps={PAGE_SIZE}"
        f"&d-3680175-n=1&d-3680175-o=1&d-3680175-p={pg}"
        f"&d-3680175-s=deadline&searchSelect=5"
    )


def main():
    by_id = {}
    errors = []
    pages = 0
    empty_streak = 0
    for pg in range(PAGE_START, PAGE_END + 1):
        url = page_url(pg)
        try:
            r = request(url)
            records = parse_page(r.text, r.url, pg)
            pages += 1
            if not records:
                empty_streak += 1
            else:
                empty_streak = 0
            for rec in records:
                by_id.setdefault(rec["candidate_id"], rec)
            if empty_streak >= 2:
                break
        except Exception as exc:
            errors.append({"page": pg, "url": url, "error": repr(exc)})

    rows = sorted(by_id.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    for name in ("raw.jsonl", "current.jsonl"):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    stats = {
        "source": SOURCE,
        "base_url": BASE_URL,
        "page_start": PAGE_START,
        "page_end_requested": PAGE_END,
        "pages_fetched": pages,
        "current_materialized": len(rows),
        "raw_materialized": len(rows),
        "deadline_parsed": sum(1 for r in rows if r.get("deadline")),
        "buyer_parsed": sum(1 for r in rows if r.get("buyer")),
        "errors": errors,
        "generated_at": NOW.isoformat(),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors and not rows:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
