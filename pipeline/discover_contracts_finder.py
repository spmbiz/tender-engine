from __future__ import annotations

import json
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/contracts_finder"))
OUT.mkdir(parents=True, exist_ok=True)
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "30"))
WINDOW_INDEX = max(0, int(os.getenv("CF_WINDOW_INDEX", "0")))
WINDOW_TOTAL = max(1, int(os.getenv("CF_WINDOW_TOTAL", "1")))
PAGE_LIMIT = min(100, max(1, int(os.getenv("PAGE_LIMIT", "100"))))
MAX_PAGES = int(os.getenv("MAX_PAGES", "120"))
REQUEST_RETRIES = max(1, int(os.getenv("CF_REQUEST_RETRIES", "4")))
RATE_LIMIT_COOLDOWN = max(300, int(os.getenv("CF_403_COOLDOWN_SECONDS", "300")))
NOW = datetime.now(timezone.utc)
HISTORY_START = NOW - timedelta(days=LOOKBACK_DAYS)
SPAN_DAYS = max(1, math.ceil(LOOKBACK_DAYS / WINDOW_TOTAL))
END = NOW - timedelta(days=WINDOW_INDEX * SPAN_DAYS)
START = max(HISTORY_START, END - timedelta(days=SPAN_DAYS))
BASE = "https://www.contractsfinder.service.gov.uk/"

s = requests.Session()
s.headers.update({"User-Agent": "Tender-Engine/3.2 public procurement research"})
url = (
    BASE
    + "Published/Notices/OCDS/Search?"
    + f"publishedFrom={START.isoformat().replace('+00:00','Z')}&"
    + f"publishedTo={END.isoformat().replace('+00:00','Z')}&stages=tender&limit={PAGE_LIMIT}"
)

seen: set[str] = set()
records: list[dict] = []
pages = 0
errors: list[dict] = []
retry_events: list[dict] = []

for _ in range(MAX_PAGES):
    data = None
    last_exc = None
    last_response = None
    for attempt in range(REQUEST_RETRIES):
        try:
            r = s.get(url, timeout=45)
            last_response = r
            if r.status_code in (403, 429) or r.status_code >= 500:
                if attempt + 1 < REQUEST_RETRIES:
                    if r.status_code == 403:
                        # Contracts Finder explicitly documents 403 as its rate-limit
                        # response and asks clients to stop requests for five minutes.
                        wait = RATE_LIMIT_COOLDOWN + random.uniform(0.0, 8.0) + WINDOW_INDEX
                    else:
                        wait = min(30.0, 1.5 * (2 ** attempt))
                        try:
                            wait = max(wait, float(r.headers.get("Retry-After", "0")))
                        except Exception:
                            pass
                    retry_events.append({"url": url, "attempt": attempt + 1, "status": r.status_code, "wait_seconds": wait})
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            data = r.json()
            pages += 1
            break
        except Exception as exc:
            last_exc = exc
            status = getattr(last_response, "status_code", None)
            if attempt + 1 < REQUEST_RETRIES and (status in (403, 408, 425, 429) or status is None or (isinstance(status, int) and status >= 500)):
                if status == 403:
                    wait = RATE_LIMIT_COOLDOWN + random.uniform(0.0, 8.0) + WINDOW_INDEX
                else:
                    wait = min(30.0, 1.5 * (2 ** attempt))
                retry_events.append({"url": url, "attempt": attempt + 1, "status": status, "wait_seconds": wait, "error": repr(exc)})
                time.sleep(wait)
                continue
            break
    if data is None:
        errors.append({"url": url, "error": repr(last_exc) if last_exc else "request_failed", "status": getattr(last_response, "status_code", None)})
        break

    for rel in data.get("releases") or []:
        rid = rel.get("id") or rel.get("ocid")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        tender = rel.get("tender") or {}
        period = tender.get("tenderPeriod") or {}
        deadline_raw = period.get("endDate")
        deadline = None
        if deadline_raw:
            try:
                deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
            except Exception:
                pass
        current = not deadline or deadline >= NOW
        parties = rel.get("parties") or []
        buyers = [p.get("name") for p in parties if "buyer" in (p.get("roles") or []) and p.get("name")]
        docs = []
        for d in tender.get("documents") or []:
            if d.get("url"):
                docs.append(
                    {
                        "title": d.get("title"),
                        "url": d.get("url"),
                        "format": d.get("format"),
                        "description": d.get("description"),
                    }
                )
        value = tender.get("value") or {}
        records.append(
            {
                "candidate_id": f"CF:{rel.get('ocid') or rid}",
                "source": "UK_CONTRACTS_FINDER",
                "portal": "UK_CONTRACTS_FINDER",
                "release_id": rid,
                "ocid": rel.get("ocid"),
                "title": tender.get("title") or "",
                "buyer": buyers[0] if buyers else None,
                "deadline": deadline.isoformat() if deadline else None,
                "current": current,
                "notice_url": tender.get("id") if str(tender.get("id") or "").startswith("http") else None,
                "estimated_value": value.get("amount"),
                "currency": value.get("currency"),
                "description": tender.get("description") or "",
                "procurement_method": tender.get("procurementMethod"),
                "procurement_method_details": tender.get("procurementMethodDetails"),
                "suitability": tender.get("suitability") or {},
                "documents": docs,
                "route": {"document_urls": [d["url"] for d in docs]},
                "published_window_start": START.isoformat(),
                "published_window_end": END.isoformat(),
                "discovered_at": NOW.isoformat(),
            }
        )

    nxt = (data.get("links") or {}).get("next") or data.get("next")
    if not nxt:
        cursor = data.get("cursor") or data.get("nextCursor")
        if cursor:
            nxt = (
                BASE
                + "Published/Notices/OCDS/Search?"
                + f"publishedFrom={START.isoformat().replace('+00:00','Z')}&"
                + f"publishedTo={END.isoformat().replace('+00:00','Z')}&stages=tender&limit={PAGE_LIMIT}&cursor={cursor}"
            )
    if not nxt:
        break
    url = urljoin(BASE, nxt)
    time.sleep(0.08)

raw_path = OUT / "raw.jsonl"
with raw_path.open("w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

current = [r for r in records if r.get("current")]
with (OUT / "current.jsonl").open("w", encoding="utf-8") as f:
    for rec in current:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

stats = {
    "source": "UK_CONTRACTS_FINDER",
    "window_index": WINDOW_INDEX,
    "window_total": WINDOW_TOTAL,
    "window_start": START.isoformat(),
    "window_end": END.isoformat(),
    "pages": pages,
    "raw_materialized": len(records),
    "current_materialized": len(current),
    "lookback_days": LOOKBACK_DAYS,
    "retry_events": retry_events,
    "rate_limit_events": sum(1 for x in retry_events if x.get("status") in (403, 429)),
    "errors": errors,
    "generated_at": NOW.isoformat(),
}
(OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(stats, indent=2, ensure_ascii=False))
