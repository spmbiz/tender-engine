from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/contracts_finder"))
OUT.mkdir(parents=True, exist_ok=True)
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "365"))
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "100"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "120"))
NOW = datetime.now(timezone.utc)
START = NOW - timedelta(days=LOOKBACK_DAYS)
BASE = "https://www.contractsfinder.service.gov.uk/"

s = requests.Session()
s.headers.update({"User-Agent": "Tender-Engine/2.0 public procurement research"})
url = (
    BASE
    + "Published/Notices/OCDS/Search?"
    + f"publishedFrom={START.isoformat().replace('+00:00','Z')}&"
    + f"publishedTo={NOW.isoformat().replace('+00:00','Z')}&stages=tender&limit={PAGE_LIMIT}"
)

seen: set[str] = set()
records: list[dict] = []
pages = 0
errors: list[dict] = []

for _ in range(MAX_PAGES):
    try:
        r = s.get(url, timeout=45)
        r.raise_for_status()
        data = r.json()
        pages += 1
    except Exception as exc:
        errors.append({"url": url, "error": repr(exc)})
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
        if deadline and deadline < NOW:
            current = False
        else:
            current = True
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
                + f"publishedTo={NOW.isoformat().replace('+00:00','Z')}&stages=tender&limit={PAGE_LIMIT}&cursor={cursor}"
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
    "pages": pages,
    "raw_materialized": len(records),
    "current_materialized": len(current),
    "lookback_days": LOOKBACK_DAYS,
    "errors": errors,
    "generated_at": NOW.isoformat(),
}
(OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(stats, indent=2, ensure_ascii=False))
