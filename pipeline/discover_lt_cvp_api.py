from __future__ import annotations

"""Lithuania CVP IS public procurement discovery.

VPT publicly documents the POST export endpoint and API key. The source contains
migrated records and occasionally malformed dates, so currentness is deliberately
fail-closed: only a valid future submission deadline promotes a record into the
live candidate set. Missing or malformed deadlines remain non-current/UNKNOWN.

Traversal is exhaustion-first. Legacy workflow page caps are ignored unless
LT_CVP_ALLOW_PAGE_CAP=1 is deliberately set. A runtime budget is used instead so
hosted runners retain enough time to persist an explicit incomplete checkpoint.
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ENDPOINT = "https://viesiejipirkimai.lt/epps-integration/api/cft-details-export"
PUBLIC_DOC_API_KEY = "acec29bd-687c-4609-b211-c01b6cf51b55"
UA = "Tender-Engine/5.6 (+public procurement research; Lithuanian VPT public API)"


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def parse_source_dt(value: Any) -> datetime | None:
    """Parse known CVP IS date shapes and reject obviously corrupted years."""
    s = clean(value)
    if not s:
        return None
    formats = (
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(s.replace("Z", "+0000"), fmt)
            if not (2000 <= dt.year <= 2100):
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if not (2000 <= dt.year <= 2100):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def parse_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(" ", "").replace(",", ".")
        return float(value)
    except Exception:
        return None


def cpv_list(value: Any) -> list[str]:
    if isinstance(value, list):
        candidates = [clean(v) for v in value]
    else:
        candidates = [x for x in re.split(r"[,;|\s]+", clean(value)) if x]
    out: list[str] = []
    for candidate in candidates:
        match = re.search(r"\b\d{8}(?:-\d)?\b", candidate)
        code = match.group(0) if match else candidate
        if code and code not in out:
            out.append(code)
    return out


def fetch_page(session: requests.Session, *, page_num: int, page_size: int) -> list[dict[str, Any]]:
    key = os.getenv("LT_CVP_API_KEY", PUBLIC_DOC_API_KEY).strip()
    if not key:
        raise RuntimeError("LT_CVP_API_KEY is empty")
    last: Exception | None = None
    for attempt in range(5):
        try:
            response = session.post(
                ENDPOINT,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Content-Type": "application/json",
                    "apiKey": key,
                    "User-Agent": UA,
                },
                json={"pageSize": page_size, "pageNum": page_num},
                timeout=60,
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < 5:
                time.sleep(min(16, 2 ** attempt))
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"unexpected CVP payload type: {type(payload).__name__}")
            return [row for row in payload if isinstance(row, dict)]
        except Exception as exc:
            last = exc
            if attempt + 1 < 5:
                time.sleep(min(16, 2 ** attempt))
    raise RuntimeError(f"Lithuania CVP page {page_num} failed: {last!r}")


def normalize_row(row: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    source_id = clean(row.get("id"))
    title = clean(row.get("title"))
    if not source_id or not title:
        return None

    deadline = parse_source_dt(row.get("tenderSubmissionDeadline"))
    published = parse_source_dt(row.get("datePublished"))
    award_date = parse_source_dt(row.get("awardDate") or row.get("contractAwardDate"))
    status = clean(row.get("status"))
    current = bool(deadline and deadline >= now)
    date_quality = {
        "published": "VALID" if published else ("MISSING" if not clean(row.get("datePublished")) else "INVALID_SOURCE_VALUE"),
        "deadline": "VALID" if deadline else ("MISSING" if not clean(row.get("tenderSubmissionDeadline")) else "INVALID_SOURCE_VALUE"),
    }
    ted_link = clean(row.get("tedLink")) or None
    buyer_id = clean(row.get("caNumber")) or None
    cpvs = cpv_list(row.get("cpvCodes"))

    return {
        "candidate_id": f"LT-CVP:{source_id}",
        "source": "LT_CVP_API",
        "portal": "LT_CVP_IS",
        "grain": "NOTICE_FIRST_TENDER",
        "notice_id": source_id,
        "procedure_id": source_id,
        "title": title,
        "description": clean(row.get("description")),
        "buyer": clean(row.get("caName")) or None,
        "buyer_id": buyer_id,
        "country": "LT",
        "cpv": cpvs,
        "published": published.isoformat() if published else None,
        "deadline": deadline.isoformat() if deadline else None,
        "current": current,
        "currentness_evidence": "VALID_FUTURE_SUBMISSION_DEADLINE" if current else "DEADLINE_NOT_FUTURE_OR_UNKNOWN",
        "date_quality": date_quality,
        "status": status or None,
        "procedure": clean(row.get("procedure")) or None,
        "procurement_type": clean(row.get("procurementType")) or None,
        "directive": clean(row.get("directive")) or None,
        "evaluation_mechanism": clean(row.get("evaluationMechanism")) or None,
        "estimated_value": parse_money(row.get("estimatedValue")),
        "currency": "EUR" if row.get("estimatedValue") not in (None, "") else None,
        "nuts": clean(row.get("nutsCode")) or None,
        "above_threshold": row.get("aboveThreshold") if isinstance(row.get("aboveThreshold"), bool) else None,
        "has_lots": row.get("contractAwardedInLots") if isinstance(row.get("contractAwardedInLots"), bool) else None,
        "contract_duration": clean(row.get("contractDuration")) or None,
        "eu_funding": row.get("euFunding") if isinstance(row.get("euFunding"), bool) else None,
        "ted_link": ted_link,
        "award_date": award_date.isoformat() if award_date else None,
        "route": {
            "document_urls": [],
            "route_status": "TED_REFERENCE_AVAILABLE" if ted_link else "LT_CVP_API_RECORD_ONLY",
        },
        "source_record": row,
        "observed_at": now.isoformat(),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/LT_CVP_API")))
    ap.add_argument("--page-size", type=int, default=int(os.getenv("LT_CVP_PAGE_SIZE", "500")))
    ap.add_argument("--max-pages", type=int, default=int(os.getenv("LT_CVP_MAX_PAGES", "20")), help="Legacy emergency cap; ignored by default unless LT_CVP_ALLOW_PAGE_CAP=1")
    ap.add_argument("--max-runtime-seconds", type=int, default=int(os.getenv("LT_CVP_MAX_RUNTIME_SECONDS", "1000")))
    args = ap.parse_args()

    page_size = max(1, min(2000, args.page_size))
    allow_page_cap = os.getenv("LT_CVP_ALLOW_PAGE_CAP", "0").strip().lower() in {"1", "true", "yes"}
    max_pages = max(1, args.max_pages) if allow_page_cap else 0
    max_runtime = max(60, int(args.max_runtime_seconds))
    now = datetime.now(timezone.utc)
    started = time.monotonic()
    session = requests.Session()
    records: dict[str, dict[str, Any]] = {}
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    invalid_dates = 0
    exhausted = False
    truncated_by_page_cap = False
    truncated_by_runtime_budget = False
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "raw.jsonl"
    current_path = out / "current.jsonl"
    stats_path = out / "stats.json"
    raw_path.write_text("", encoding="utf-8")
    current_path.write_text("", encoding="utf-8")

    def checkpoint(state: str) -> None:
        current_count = sum(1 for row in records.values() if row.get("current"))
        payload = {
            "source": "LT_CVP_API",
            "portal": "LT_CVP_IS",
            "grain": "NOTICE_FIRST_TENDER",
            "raw_materialized": len(records),
            "current_materialized": current_count,
            "pages_fetched": len(telemetry),
            "page_size": page_size,
            "legacy_requested_max_pages": args.max_pages,
            "page_cap_enabled": allow_page_cap,
            "max_pages": max_pages or None,
            "max_runtime_seconds": max_runtime,
            "runtime_seconds": round(time.monotonic() - started, 3),
            "exhausted": False,
            "enumeration_exhausted": False,
            "enumeration_complete": False,
            "truncated_by_page_cap": truncated_by_page_cap,
            "truncated_by_runtime_budget": truncated_by_runtime_budget,
            "invalid_source_dates_observed": invalid_dates,
            "errors": errors,
            "telemetry": telemetry[-25:],
            "checkpoint": True,
            "checkpoint_state": state,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_url": ENDPOINT,
            "semantics": "Checkpoint only. Exhaustive traversal is proven only by an empty/short API page; legacy page caps are disabled unless explicitly enabled.",
        }
        tmp = out / "stats.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(stats_path)

    checkpoint("STARTED")
    page_num = 1
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= max_runtime:
            truncated_by_runtime_budget = True
            checkpoint("RUNTIME_BUDGET")
            break
        if max_pages and page_num > max_pages:
            truncated_by_page_cap = True
            checkpoint("HARD_PAGE_CAP")
            break
        try:
            rows = fetch_page(session, page_num=page_num, page_size=page_size)
        except Exception as exc:
            errors.append({"page": page_num, "error": repr(exc)})
            checkpoint("REQUEST_FAILED")
            break

        telemetry.append({"page": page_num, "rows": len(rows)})
        if not rows:
            exhausted = True
            checkpoint("EXHAUSTED_EMPTY_PAGE")
            break

        newly_materialized: list[dict[str, Any]] = []
        for row in rows:
            normalized = normalize_row(row, now)
            if not normalized:
                continue
            invalid_dates += sum(v == "INVALID_SOURCE_VALUE" for v in normalized["date_quality"].values())
            cid = normalized["candidate_id"]
            if cid not in records:
                newly_materialized.append(normalized)
            records[cid] = normalized

        if newly_materialized:
            with raw_path.open("a", encoding="utf-8") as handle:
                for normalized in newly_materialized:
                    handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            with current_path.open("a", encoding="utf-8") as handle:
                for normalized in newly_materialized:
                    if normalized.get("current"):
                        handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")

        if len(rows) < page_size:
            exhausted = True
            checkpoint("EXHAUSTED_SHORT_PAGE")
            break
        checkpoint("PAGE_COMMITTED")
        page_num += 1

    raw = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [row for row in raw if row.get("current")]
    # Final rewrite removes any possible duplicate/stale append artifact while
    # preserving the checkpoint files during traversal interruption.
    write_jsonl(raw_path, raw)
    write_jsonl(current_path, current)
    enumeration_complete = bool(exhausted and not errors and not truncated_by_page_cap and not truncated_by_runtime_budget)
    stats = {
        "source": "LT_CVP_API",
        "portal": "LT_CVP_IS",
        "grain": "NOTICE_FIRST_TENDER",
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "pages_fetched": len(telemetry),
        "page_size": page_size,
        "legacy_requested_max_pages": args.max_pages,
        "page_cap_enabled": allow_page_cap,
        "max_pages": max_pages or None,
        "max_runtime_seconds": max_runtime,
        "runtime_seconds": round(time.monotonic() - started, 3),
        "exhausted": exhausted,
        "enumeration_exhausted": exhausted,
        "enumeration_complete": enumeration_complete,
        "truncated_by_page_cap": truncated_by_page_cap,
        "truncated_by_runtime_budget": truncated_by_runtime_budget,
        "invalid_source_dates_observed": invalid_dates,
        "errors": errors,
        "telemetry": telemetry,
        "checkpoint": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": ENDPOINT,
        "semantics": "Traversal is exhaustion-first. A short/empty API page proves enumeration exhaustion. Runtime budget, explicit emergency page cap, or request errors keep enumeration_complete false. Currentness remains fail-closed and requires a valid future tenderSubmissionDeadline.",
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not raw:
        raise SystemExit(2)


if __name__ == "__main__":
    main()