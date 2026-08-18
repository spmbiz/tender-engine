from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/ted"))
OUT.mkdir(parents=True, exist_ok=True)
API = "https://api.ted.europa.eu/v3/notices/search"
SCOPE = os.getenv("TED_SCOPE", "ACTIVE").strip().upper()
LIMIT = min(250, max(1, int(os.getenv("TED_LIMIT", "250"))))
LOOKBACK_DAYS = max(1, int(os.getenv("TED_LOOKBACK_DAYS", "10")))
REQUEST_RETRIES = max(1, int(os.getenv("TED_REQUEST_RETRIES", "7")))
BACKOFF_BASE_SECONDS = max(0.5, float(os.getenv("TED_BACKOFF_BASE_SECONDS", "3")))
PAGE_DELAY_SECONDS = max(0.0, float(os.getenv("TED_PAGE_DELAY_SECONDS", "0.25")))
# ACTIVE scope is itself the authoritative live-universe filter for competition
# notices. Publication-date lookbacks are therefore disabled by default for
# ACTIVE discovery. Set TED_ACTIVE_RECENT_ONLY=1 only for a deliberately partial
# diagnostic run.
ACTIVE_RECENT_ONLY = os.getenv("TED_ACTIVE_RECENT_ONLY", "0").strip().lower() in {"1", "true", "yes"}
FULL_ACTIVE = SCOPE == "ACTIVE" and not ACTIVE_RECENT_ONLY
# Legacy workflows may still set TED_MAX_PAGES. We intentionally ignore that
# cap in FULL_ACTIVE mode; use TED_HARD_MAX_PAGES explicitly if an emergency
# safety cap is required. Any hit is surfaced as incomplete coverage.
LEGACY_MAX_PAGES = max(0, int(os.getenv("TED_MAX_PAGES", "48")))
HARD_MAX_PAGES = max(0, int(os.getenv("TED_HARD_MAX_PAGES", "0"))) if FULL_ACTIVE else LEGACY_MAX_PAGES
NOW = datetime.now(timezone.utc)
START = NOW - timedelta(days=LOOKBACK_DAYS)
START_DAY = START.date()
RECENT_QUERY = f"PD = ({START:%Y%m%d} <> {NOW:%Y%m%d}) AND form-type = competition"
DEFAULT_QUERY = "form-type = competition" if FULL_ACTIVE else RECENT_QUERY
QUERY = os.getenv("TED_QUERY", DEFAULT_QUERY)

FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "publication-date",
    "deadline",
    "deadline-receipt-request",
    "deadline-receipt-tender-date-lot",
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


def publication_day(value):
    if value is None:
        return None
    s = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc).date()
        except Exception:
            return None
    if re.fullmatch(r"\d{8}", s):
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except Exception:
            return None
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


def retry_after_seconds(resp, attempt: int) -> float:
    raw = (resp.headers.get("Retry-After") if resp is not None else None) or ""
    try:
        explicit = float(raw)
    except Exception:
        explicit = 0.0
    exponential = min(60.0, BACKOFF_BASE_SECONDS * (2 ** attempt))
    return max(explicit, exponential)


def run() -> dict:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "User-Agent": "Tender-Engine/6.3 public procurement research"})
    rows = []
    seen = set()
    token = None
    errors = []
    retry_events = []
    page_count = 0
    total_reported = None
    source_items_seen = 0
    truncated_by_page_cap = False
    exhausted = False

    # Checkpoint every committed page before requesting the next one. If a long
    # ACTIVE traversal is interrupted by runner/step termination, already-read
    # notices and explicit incomplete coverage survive instead of vanishing.
    active_path = OUT / "active.jsonl"
    current_path = OUT / "current.jsonl"
    stats_path = OUT / "stats.json"
    active_path.write_text("", encoding="utf-8")
    current_path.write_text("", encoding="utf-8")

    def checkpoint(state: str, *, next_token_present: bool = False) -> None:
        current_count = sum(1 for r in rows if r.get("current"))
        payload = {
            "source": "TED",
            "scope": SCOPE,
            "enumeration_mode": "FULL_ACTIVE_COMPETITION" if FULL_ACTIVE else "RECENT_PUBLICATION_WINDOW",
            "query": QUERY,
            "lookback_days": None if FULL_ACTIVE else LOOKBACK_DAYS,
            "window_start_day": None if FULL_ACTIVE else START_DAY.isoformat(),
            "window_end_day": NOW.date().isoformat(),
            "pages": page_count,
            "limit": LIMIT,
            "hard_max_pages": HARD_MAX_PAGES,
            "total_reported": total_reported,
            "source_items_seen": source_items_seen,
            "materialized_unique": len(rows),
            "current_materialized": current_count,
            "future_deadline_records": sum(1 for r in rows if r.get("has_future_deadline")),
            "enumeration_exhausted": False,
            "enumeration_complete": False,
            "truncated_by_page_cap": truncated_by_page_cap,
            "request_retries": REQUEST_RETRIES,
            "page_delay_seconds": PAGE_DELAY_SECONDS,
            "retry_events": retry_events,
            "rate_limit_events": sum(1 for x in retry_events if x.get("status") == 429),
            "errors": errors,
            "checkpoint": True,
            "checkpoint_state": state,
            "next_token_present": bool(next_token_present),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "semantics": "Checkpoint only: partial TED ACTIVE traversal is durable but never complete until iteration-token exhaustion is proven.",
        }
        tmp = OUT / "stats.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(stats_path)

    checkpoint("STARTED")

    page_no = 0
    while True:
        page_no += 1
        if HARD_MAX_PAGES and page_no > HARD_MAX_PAGES:
            truncated_by_page_cap = True
            checkpoint("HARD_PAGE_CAP", next_token_present=bool(token))
            break

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

        data = None
        final_exc = None
        final_response = None
        for attempt in range(REQUEST_RETRIES):
            resp = None
            try:
                resp = session.post(API, data=json.dumps(body), timeout=60)
                final_response = resp
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    if attempt + 1 < REQUEST_RETRIES:
                        wait = retry_after_seconds(resp, attempt)
                        retry_events.append({"page": page_no, "attempt": attempt + 1, "status": resp.status_code, "wait_seconds": wait})
                        checkpoint("RETRY_WAIT", next_token_present=bool(token))
                        time.sleep(wait)
                        continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                final_exc = exc
                status = getattr(resp, "status_code", None)
                retryable = status in (408, 425, 429) or (isinstance(status, int) and status >= 500) or status is None
                if retryable and attempt + 1 < REQUEST_RETRIES:
                    wait = retry_after_seconds(resp, attempt)
                    retry_events.append({"page": page_no, "attempt": attempt + 1, "status": status, "wait_seconds": wait, "error": repr(exc)})
                    checkpoint("RETRY_WAIT", next_token_present=bool(token))
                    time.sleep(wait)
                    continue
                break

        if data is None:
            errors.append({
                "page": page_no,
                "error": repr(final_exc) if final_exc else "request_failed",
                "status": getattr(final_response, "status_code", None),
                "response": getattr(final_response, "text", "")[:2000] if final_response is not None else None,
            })
            checkpoint("REQUEST_FAILED", next_token_present=bool(token))
            break

        page_count += 1
        total_reported = data.get("totalNoticeCount") or data.get("total") or data.get("totalCount") or total_reported
        items = data.get("notices") or data.get("results") or data.get("items") or []
        if not isinstance(items, list):
            errors.append({"page": page_no, "error": "unrecognized_items_shape", "keys": list(data.keys())})
            checkpoint("BAD_ITEMS_SHAPE", next_token_present=bool(token))
            break
        source_items_seen += len(items)
        page_row_start = len(rows)

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

            publication_date_raw = scalar(first_field(item, "publication-date"))
            pday = publication_day(publication_date_raw)
            if not FULL_ACTIVE and pday and pday < START_DAY:
                continue

            deadline_values = []
            for name in ("deadline", "deadline-receipt-request", "deadline-receipt-tender-date-lot"):
                deadline_values.extend(flatten_values(first_field(item, name)))
            parsed_deadlines = [parse_date(v) for v in deadline_values]
            parsed_deadlines = [d for d in parsed_deadlines if d]
            future_deadlines = [d for d in parsed_deadlines if d >= NOW]
            deadline = min(future_deadlines).isoformat() if future_deadlines else (max(parsed_deadlines).isoformat() if parsed_deadlines else None)
            current = True if FULL_ACTIVE else bool(not parsed_deadlines or future_deadlines)

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

            rows.append({
                "candidate_id": f"TED:{pub}",
                "source": "TED",
                "portal": "TED",
                "publication_number": str(pub),
                "title": str(title or ""),
                "buyer": str(buyer or "") or None,
                "deadline": deadline,
                "current": current,
                "currentness_evidence": "TED_ACTIVE_COMPETITION_SCOPE" if FULL_ACTIVE else "RECENT_WINDOW_PLUS_DEADLINE",
                "has_future_deadline": bool(future_deadlines),
                "notice_url": notice_url,
                "estimated_value": value,
                "currency": str(currency or "") or None,
                "description": str(desc),
                "publication_date": publication_date_raw,
                "procedure_type": scalar(first_field(item, "procedure-type")),
                "notice_type": scalar(first_field(item, "notice-type")),
                "form_type": scalar(first_field(item, "form-type")),
                "classification_cpv": flatten_values(first_field(item, "classification-cpv")),
                "route": {"publication_number": str(pub)},
                "discovered_at": NOW.isoformat(),
            })

        page_rows = rows[page_row_start:]
        if page_rows:
            with active_path.open("a", encoding="utf-8") as f:
                for rec in page_rows:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            with current_path.open("a", encoding="utf-8") as f:
                for rec in page_rows:
                    if rec.get("current"):
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        next_token = data.get("iterationNextToken") or data.get("nextToken") or data.get("nextPageToken")
        if not next_token or not items:
            exhausted = True
            token = None
            checkpoint("EXHAUSTED", next_token_present=False)
            break
        token = next_token
        checkpoint("PAGE_COMMITTED", next_token_present=True)
        if PAGE_DELAY_SECONDS:
            time.sleep(PAGE_DELAY_SECONDS)

    current_rows = [r for r in rows if r.get("current")]
    enumeration_complete = bool(exhausted and not errors and not truncated_by_page_cap)
    if total_reported is not None:
        try:
            enumeration_complete = enumeration_complete and source_items_seen >= int(total_reported)
        except Exception:
            pass

    stats = {
        "source": "TED",
        "scope": SCOPE,
        "enumeration_mode": "FULL_ACTIVE_COMPETITION" if FULL_ACTIVE else "RECENT_PUBLICATION_WINDOW",
        "query": QUERY,
        "lookback_days": None if FULL_ACTIVE else LOOKBACK_DAYS,
        "window_start_day": None if FULL_ACTIVE else START_DAY.isoformat(),
        "window_end_day": NOW.date().isoformat(),
        "pages": page_count,
        "limit": LIMIT,
        "hard_max_pages": HARD_MAX_PAGES,
        "total_reported": total_reported,
        "source_items_seen": source_items_seen,
        "materialized_unique": len(rows),
        "current_materialized": len(current_rows),
        "future_deadline_records": sum(1 for r in rows if r.get("has_future_deadline")),
        "enumeration_exhausted": exhausted,
        "enumeration_complete": enumeration_complete,
        "truncated_by_page_cap": truncated_by_page_cap,
        "request_retries": REQUEST_RETRIES,
        "page_delay_seconds": PAGE_DELAY_SECONDS,
        "retry_events": retry_events,
        "rate_limit_events": sum(1 for x in retry_events if x.get("status") == 429),
        "errors": errors,
        "checkpoint": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": "FULL_ACTIVE_COMPETITION enumerates TED ACTIVE-scope competition notices to iteration-token exhaustion; no publication-date lookback is applied. A hard page cap, request error, or reported-count mismatch makes enumeration_complete false.",
    }
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return stats


if __name__ == "__main__":
    run()