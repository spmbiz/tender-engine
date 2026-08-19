from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/GR_KHMDHS"))
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc)
BASE = "https://cerpp.eprocurement.gov.gr/khmdhs-opendata"
UA = "Tender-Engine/7.2 (+official Greece KIMDIS Open Data; paced future-deadline shards)"
WINDOW_DAYS = max(1, min(180, int(os.getenv("GR_FINAL_WINDOW_DAYS", "180"))))
HORIZON_YEAR = max(NOW.year, min(2100, int(os.getenv("GR_FINAL_HORIZON_YEAR", "2100"))))
WORKERS = max(1, min(5, int(os.getenv("GR_WORKERS", "2"))))
RETRIES = max(1, min(10, int(os.getenv("GR_RETRIES", "7"))))
MIN_REQUEST_INTERVAL = max(0.18, float(os.getenv("GR_MIN_REQUEST_INTERVAL_SECONDS", "0.45")))
MAX_RETRY_AFTER = max(1.0, float(os.getenv("GR_MAX_RETRY_AFTER_SECONDS", "90")))

_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def kv(value: Any):
    if isinstance(value, dict):
        return value.get("value") or value.get("name") or value.get("label") or value.get("key")
    return value


def pdt(value: Any) -> datetime | None:
    s = clean(value)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def cpvs(obj: dict[str, Any]) -> list[str]:
    out: list[str] = []
    details = obj.get("objectDetails") or obj.get("objectDetailsList") or []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        for cpv in detail.get("cpvs") or []:
            value = clean(kv(cpv))
            if value and value not in out:
                out.append(value)
    return out


def description(obj: dict[str, Any]) -> str:
    parts = []
    for detail in obj.get("objectDetails") or obj.get("objectDetailsList") or []:
        if isinstance(detail, dict) and clean(detail.get("shortDescription")):
            parts.append(clean(detail.get("shortDescription")))
    return " | ".join(parts)


def window_manifest() -> list[tuple[date, date]]:
    cursor = NOW.date()
    final = date(HORIZON_YEAR, 12, 31)
    windows: list[tuple[date, date]] = []
    while cursor <= final:
        end = min(final, cursor + timedelta(days=WINDOW_DAYS - 1))
        windows.append((cursor, end))
        cursor = end + timedelta(days=1)
    return windows


def pace_request() -> None:
    """Serialize request starts across worker threads below the publisher limit."""
    global _NEXT_REQUEST_AT
    with _RATE_LOCK:
        now = time.monotonic()
        if _NEXT_REQUEST_AT > now:
            time.sleep(_NEXT_REQUEST_AT - now)
            now = time.monotonic()
        _NEXT_REQUEST_AT = max(now, _NEXT_REQUEST_AT) + MIN_REQUEST_INTERVAL


def retry_after_seconds(response: requests.Response) -> float | None:
    raw = clean(response.headers.get("Retry-After"))
    if not raw:
        return None
    try:
        return max(0.0, min(MAX_RETRY_AFTER, float(raw)))
    except Exception:
        pass
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(MAX_RETRY_AFTER, seconds))
    except Exception:
        return None


def verified_no_data_404(response: requests.Response, page: int) -> bool:
    """Accept 404 as an empty window only when the publisher explicitly says so."""
    if response.status_code != 404 or page != 0:
        return False
    candidates: list[str] = []
    try:
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("error", "message", "detail", "title"):
                if payload.get(key) is not None:
                    candidates.append(clean(payload.get(key)))
        elif isinstance(payload, str):
            candidates.append(clean(payload))
    except Exception:
        pass
    candidates.append(clean(response.text))
    haystack = " | ".join(x for x in candidates if x).lower()
    return any(
        phrase in haystack
        for phrase in (
            "no data found for the given criteria",
            "no data found",
            "δεν βρέθηκαν δεδομένα",
            "δεν βρεθηκαν δεδομενα",
        )
    )


def fetch_page(session: requests.Session, start: date, end: date, page: int) -> dict[str, Any]:
    payload = {
        "finalDateFrom": start.strftime("%Y-%m-%d 00:00"),
        "finalDateTo": end.strftime("%Y-%m-%d 23:59"),
        "isModified": False,
    }
    last: Exception | None = None
    for attempt in range(RETRIES):
        response: requests.Response | None = None
        try:
            pace_request()
            response = session.post(
                f"{BASE}/notice",
                params={"page": page},
                json=payload,
                timeout=90,
            )
            if verified_no_data_404(response, page):
                return {
                    "content": [],
                    "totalPages": 0,
                    "totalElements": 0,
                    "last": True,
                    "empty": True,
                    "_verified_no_data_404": True,
                }
            if response.status_code == 429:
                retry_after = retry_after_seconds(response)
                wait = retry_after if retry_after is not None else min(60.0, 3.0 * (attempt + 1) ** 2)
                last = RuntimeError(f"HTTP_429 retry_after={retry_after!r}")
                if attempt + 1 < RETRIES:
                    time.sleep(wait)
                    continue
                raise last
            if response.status_code in {408, 425, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"NON_OBJECT_RESPONSE:{type(data).__name__}")
            return data
        except Exception as exc:
            last = exc
            if attempt + 1 < RETRIES:
                retry_after = retry_after_seconds(response) if response is not None else None
                time.sleep(retry_after if retry_after is not None else min(30.0, 1.5 * (2**attempt)))
    raise RuntimeError(f"GR_KHMDHS_PAGE_FAILED {start}/{end} page={page}: {last!r}")


def harvest_window(start: date, end: date) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    rows: list[dict[str, Any]] = []
    page = 0
    page_telemetry: list[dict[str, Any]] = []
    total_pages: int | None = None
    total_elements: int | None = None
    verified_empty_404 = False
    while True:
        data = fetch_page(session, start, end, page)
        content = data.get("content")
        if not isinstance(content, list):
            raise RuntimeError(f"GR_KHMDHS_CONTENT_NOT_LIST {start}/{end} page={page}")
        observed_total_pages = int(data.get("totalPages") or 0)
        observed_total_elements = int(data.get("totalElements") or 0)
        verified_empty_404 = bool(data.get("_verified_no_data_404"))
        if total_pages is None:
            total_pages = observed_total_pages
            total_elements = observed_total_elements
        elif observed_total_pages != total_pages or observed_total_elements != total_elements:
            raise RuntimeError(
                f"GR_KHMDHS_PAGE_TOTAL_DRIFT {start}/{end} page={page} "
                f"pages={observed_total_pages}/{total_pages} elements={observed_total_elements}/{total_elements}"
            )
        page_telemetry.append({
            "page": page,
            "rows": len(content),
            "total_pages": observed_total_pages,
            "total_elements": observed_total_elements,
            "last": bool(data.get("last")),
            "verified_no_data_404": verified_empty_404,
        })
        rows.extend(x for x in content if isinstance(x, dict))
        if data.get("last") is True or observed_total_pages == 0 or page >= max(0, observed_total_pages - 1):
            break
        if not content:
            raise RuntimeError(f"GR_KHMDHS_PREMATURE_EMPTY_PAGE {start}/{end} page={page}")
        page += 1
    if total_elements is not None and len(rows) != total_elements:
        raise RuntimeError(
            f"GR_KHMDHS_COUNT_MISMATCH {start}/{end}: rows={len(rows)} total_elements={total_elements}"
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": rows,
        "pages": page_telemetry,
        "total_elements": total_elements or 0,
        "verified_empty_404": verified_empty_404,
        "complete": True,
    }


def normalize(obj: dict[str, Any]) -> dict[str, Any] | None:
    reference = clean(obj.get("referenceNumber"))
    title = clean(obj.get("title"))
    if not reference and not title:
        return None
    deadline = pdt(obj.get("finalSubmissionDate"))
    if not deadline:
        return None
    cancelled = bool(obj.get("cancelled") or obj.get("cancellationDate"))
    submitted = pdt(obj.get("submissionDate"))
    published = pdt(obj.get("publishedDate")) or submitted or pdt(obj.get("signedDate"))
    org = kv(obj.get("organization"))
    if not org and isinstance(obj.get("contractingData"), dict):
        org = kv(obj["contractingData"].get("unitsOperator"))
    value = obj.get("totalCostWithoutVAT")
    if value in (None, ""):
        value = obj.get("budget")
    detail = (
        "https://cerpp.eprocurement.gov.gr/upgkimdis/unprotected/home.xhtml?referenceNumber=" + quote(reference, safe="")
        if reference else None
    )
    docs = [f"{BASE}/notice/attachment/{quote(reference, safe='')}"] if reference else []
    website = clean(obj.get("biddingWebsite")) or None
    current = bool(not cancelled and deadline >= NOW)
    return {
        "candidate_id": f"GR-KHMDHS:{reference or abs(hash(title))}",
        "source": "GR_KHMDHS",
        "portal": "GR_KHMDHS",
        "grain": "NOTICE_FIRST_TENDER",
        "notice_id": reference or None,
        "title": title or reference,
        "buyer": clean(org) or None,
        "country": "GR",
        "deadline": deadline.isoformat(),
        "published": published.isoformat() if published else None,
        "current": current,
        "currentness_evidence": (
            "KIMDIS_OFFICIAL_FUTURE_FINAL_SUBMISSION_DATE_AND_NOT_CANCELLED"
            if current else "KIMDIS_CANCELLED_OR_DEADLINE_NOT_FUTURE"
        ),
        "notice_url": detail,
        "estimated_value": value,
        "currency": "EUR",
        "cpv": cpvs(obj),
        "description": description(obj),
        "procedure": clean(kv(obj.get("typeOfProcedure") or obj.get("procedureType"))) or None,
        "contract_type": clean(kv(obj.get("contractType"))) or None,
        "notice_type": clean(kv(obj.get("noticeType"))) or None,
        "route": {
            "document_urls": docs,
            "direct_public_dce": bool(docs),
            "detail_url": detail,
            "proceeding_url": website,
        },
        "discovered_at": NOW.isoformat(),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    windows = window_manifest()
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(harvest_window, start, end): (start, end) for start, end in windows}
        for future in as_completed(futures):
            start, end = futures[future]
            try:
                result = future.result()
                rows = result.pop("rows")
                source_rows.extend(rows)
                telemetry.append(result)
            except Exception as exc:
                errors.append({"start": start.isoformat(), "end": end.isoformat(), "error": repr(exc)})

    telemetry.sort(key=lambda x: x.get("start") or "")
    completed = {(x.get("start"), x.get("end")) for x in telemetry if x.get("complete") is True}
    expected = {(a.isoformat(), b.isoformat()) for a, b in windows}
    enumeration_complete = bool(not errors and completed == expected)

    dedup: dict[str, dict[str, Any]] = {}
    normalization_drops = 0
    for obj in source_rows:
        row = normalize(obj)
        if not row:
            normalization_drops += 1
            continue
        cid = row["candidate_id"]
        old = dedup.get(cid)
        if not old or str(row.get("published") or "") >= str(old.get("published") or ""):
            dedup[cid] = row

    rows = sorted(dedup.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in rows if x.get("current")]
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)
    stats = {
        "source": "GR_KHMDHS",
        "listing_contract": "GR_KHMDHS_FUTURE_DEADLINE_WINDOWS_V3_PACED",
        "deadline_horizon_end": f"{HORIZON_YEAR}-12-31",
        "window_days": WINDOW_DAYS,
        "workers": WORKERS,
        "min_request_interval_seconds": MIN_REQUEST_INTERVAL,
        "windows_expected": len(windows),
        "windows_completed": len(completed),
        "verified_empty_404_windows": sum(1 for x in telemetry if x.get("verified_empty_404")),
        "source_rows_seen": len(source_rows),
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "normalization_drops": normalization_drops,
        "enumeration_exhausted": enumeration_complete,
        "enumeration_complete": enumeration_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": enumeration_complete and bool(current),
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "warnings": ([] if HORIZON_YEAR == 2100 else [{
            "type": "DEADLINE_HORIZON_BELOW_SCHEMA_BOUND",
            "horizon_year": HORIZON_YEAR,
        }]),
        "official_url": BASE,
        "telemetry": telemetry,
        "semantics": (
            "Official KIMDIS Open Data POST /notice only. Contiguous finalSubmissionDate windows are at most 180 days. "
            "Request starts are globally paced across workers and HTTP 429 honors Retry-After when supplied. "
            "A page-0 HTTP 404 is accepted as an exhausted empty window only when the publisher response explicitly states that no data were found for the criteria; every other 404 remains fatal. "
            "Non-empty windows require stable totalPages/totalElements and exact row-count reconciliation. Cancelled notices are excluded from current."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not enumeration_complete or not rows:
        raise SystemExit(3 if errors else 2)


if __name__ == "__main__":
    main()
