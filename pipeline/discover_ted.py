from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/ted"))
OUT.mkdir(parents=True, exist_ok=True)
API = "https://api.ted.europa.eu/v3/notices/search"
SCOPE = os.getenv("TED_SCOPE", "ACTIVE")
# Competition form covers contract notices/calls for competition rather than award/result/planning notices.
QUERY = os.getenv("TED_QUERY", "form-type = competition")
LIMIT = min(250, int(os.getenv("TED_LIMIT", "250")))
MAX_PAGES = int(os.getenv("TED_MAX_PAGES", "24"))
NOW = datetime.now(timezone.utc)

FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "publication-date",
    "deadline",
    "deadline-receipt-request",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "description-proc",
    "procedure-type",
    "notice-type",
    "form-type",
    "classification-cpv",
]


def scalar(value):
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("eng", "en", "EN", "value"):
            if key in value and value[key]:
                return scalar(value[key])
        for v in value.values():
            s = scalar(v)
            if s:
                return s
        return None
    if isinstance(value, list):
        vals = [scalar(v) for v in value]
        vals = [v for v in vals if v not in (None, "")]
        return vals[0] if vals else None
    return value


def flatten_values(value):
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(flatten_values(v))
        return out
    if isinstance(value, dict):
        out = []
        for v in value.values():
            out.extend(flatten_values(v))
        return out
    return [value]


def parse_date(value):
    if value is None:
        return None
    s = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def first_field(item: dict, *names):
    for name in names:
        if name in item and item[name] not in (None, "", [], {}):
            return item[name]
    fields = item.get("fields")
    if isinstance(fields, dict):
        for name in names:
            if name in fields and fields[name] not in (None, "", [], {}):
                return fields[name]
    return None


session = requests.Session()
session.headers.update({"Content-Type": "application/json", "User-Agent": "Tender-Engine/2.0 public procurement research"})
rows = []
seen = set()
token = None
errors = []
page_count = 0
total_reported = None

for page_no in range(1, MAX_PAGES + 1):
    body = {
        "query": QUERY,
        "fields": FIELDS,
        "limit": LIMIT,
        "scope": SCOPE,
        "checkQuerySyntax": False,
        "paginationMode": "ITERATION",
    }
    if token:
        body["iterationNextToken"] = token
    try:
        resp = session.post(API, data=json.dumps(body), timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        errors.append({"page": page_no, "error": repr(exc), "response": getattr(resp, "text", "")[:2000] if "resp" in locals() else None})
        break

    page_count += 1
    total_reported = data.get("totalNoticeCount") or data.get("total") or data.get("totalCount") or total_reported
    items = data.get("notices") or data.get("results") or data.get("items") or []
    if not isinstance(items, list):
        errors.append({"page": page_no, "error": "unrecognized_items_shape", "keys": list(data.keys())})
        break

    for item in items:
        if not isinstance(item, dict):
            continue
        pub = scalar(first_field(item, "publication-number", "publicationNumber"))
        if not pub:
            raw = json.dumps(item, ensure_ascii=False)
            m = re.search(r"\b\d{4,8}-20\d{2}\b", raw)
            pub = m.group(0) if m else None
        if not pub or str(pub) in seen:
            continue
        seen.add(str(pub))

        deadline_values = []
        for name in ("deadline", "deadline-receipt-request", "deadline-receipt-tender-date-lot"):
            deadline_values.extend(flatten_values(first_field(item, name)))
        parsed_deadlines = [parse_date(v) for v in deadline_values]
        parsed_deadlines = [d for d in parsed_deadlines if d]
        future_deadlines = [d for d in parsed_deadlines if d >= NOW]
        deadline = min(future_deadlines).isoformat() if future_deadlines else (max(parsed_deadlines).isoformat() if parsed_deadlines else None)
        # If TED exposes a deadline and every deadline is already past, this is not live for bidding.
        # No-deadline competition notices remain visible because qualification systems / multi-stage calls may omit BT-131 here.
        current = bool(not parsed_deadlines or future_deadlines)

        value_raw = scalar(first_field(item, "estimated-value-proc"))
        try:
            value = float(value_raw) if value_raw is not None else None
        except Exception:
            value = None
        currency = scalar(first_field(item, "estimated-value-cur-proc"))
        title = scalar(first_field(item, "notice-title"))
        buyer = scalar(first_field(item, "buyer-name"))
        desc = scalar(first_field(item, "description-proc")) or ""
        notice_url = f"https://ted.europa.eu/en/notice/-/detail/{pub}"

        rows.append(
            {
                "candidate_id": f"TED:{pub}",
                "source": "TED",
                "portal": "TED",
                "publication_number": str(pub),
                "title": str(title or ""),
                "buyer": str(buyer or "") or None,
                "deadline": deadline,
                "current": current,
                "has_future_deadline": bool(future_deadlines),
                "notice_url": notice_url,
                "estimated_value": value,
                "currency": str(currency or "") or None,
                "description": str(desc),
                "publication_date": scalar(first_field(item, "publication-date")),
                "procedure_type": scalar(first_field(item, "procedure-type")),
                "notice_type": scalar(first_field(item, "notice-type")),
                "form_type": scalar(first_field(item, "form-type")),
                "classification_cpv": flatten_values(first_field(item, "classification-cpv")),
                "route": {"publication_number": str(pub)},
                "discovered_at": NOW.isoformat(),
            }
        )

    token = data.get("iterationNextToken") or data.get("nextToken") or data.get("nextPageToken")
    if not token or not items:
        break

with (OUT / "active.jsonl").open("w", encoding="utf-8") as f:
    for rec in rows:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

current_rows = [r for r in rows if r.get("current")]
with (OUT / "current.jsonl").open("w", encoding="utf-8") as f:
    for rec in current_rows:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

stats = {
    "source": "TED",
    "scope": SCOPE,
    "query": QUERY,
    "pages": page_count,
    "limit": LIMIT,
    "total_reported": total_reported,
    "materialized_unique": len(rows),
    "current_materialized": len(current_rows),
    "future_deadline_records": sum(1 for r in rows if r.get("has_future_deadline")),
    "errors": errors,
    "generated_at": NOW.isoformat(),
}
(OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(stats, indent=2, ensure_ascii=False))
