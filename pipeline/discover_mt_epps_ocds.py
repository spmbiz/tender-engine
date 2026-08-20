from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import requests

try:
    from pipeline.ocds_release_normalizer import release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_to_candidate

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/MALTA_EPPS"))
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc)
MODE = os.getenv("DISCOVERY_MODE", "delta").strip().lower()
FIRST_MONTH = (2019, 10)
DELTA_MONTHS = max(1, min(24, int(os.getenv("MT_EPPS_DELTA_MONTHS", "6"))))
WORKERS = max(1, min(6, int(os.getenv("MT_EPPS_OCDS_WORKERS", "4"))))
RETRIES = max(1, min(8, int(os.getenv("MT_EPPS_OCDS_RETRIES", "5"))))
UA = "Tender-Engine/7.3 (+official Malta ePPS OCDS record packages; OCP Kingfisher-compatible)"

# OCP Kingfisher's maintained Malta spider uses the demowww.etenders.gov.mt
# host for this OCDS service. Prefer HTTPS where available, while retaining the
# exact maintained HTTP endpoint as a final official-host fallback.
BASE_CANDIDATES = [
    "https://demowww.etenders.gov.mt",
    "https://www.etenders.gov.mt",
    "http://demowww.etenders.gov.mt",
]
LIST_PATH = "/ocds/services/recordpackage/getrecordpackagelist"


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def month_tuple_from_url(url: str) -> tuple[int, int] | None:
    path = urlsplit(url).path.rstrip("/")
    match = re.search(r"/(20\d{2})/(\d{1,2})$", path)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if 1 <= month <= 12:
        return year, month
    return None


def month_key(value: tuple[int, int]) -> str:
    return f"{value[0]:04d}-{value[1]:02d}"


def subtract_months(year: int, month: int, count: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) - count
    return absolute // 12, absolute % 12 + 1


def iter_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        records = value.get("records")
        if isinstance(records, list):
            for record in records:
                if isinstance(record, dict):
                    yield record
            return
        if isinstance(value.get("compiledRelease"), dict):
            yield value
            return
    elif isinstance(value, list):
        for item in value:
            yield from iter_records(item)


def record_version_key(record: dict[str, Any]) -> tuple[str, str]:
    compiled = record.get("compiledRelease") if isinstance(record.get("compiledRelease"), dict) else {}
    return (
        clean(record.get("date") or compiled.get("date")),
        clean(record.get("ocid") or compiled.get("ocid")),
    )


def discover_manifest(session: requests.Session) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    attempts = []
    last_error: Exception | None = None
    for base in BASE_CANDIDATES:
        url = base + LIST_PATH
        for attempt in range(RETRIES):
            try:
                response = session.get(url, timeout=60, allow_redirects=True)
                attempts.append({
                    "base": base,
                    "attempt": attempt + 1,
                    "status": response.status_code,
                    "final_url": response.url,
                    "content_type": response.headers.get("content-type"),
                    "bytes": len(response.content),
                })
                if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                    raise RuntimeError(f"HTTP_{response.status_code}")
                response.raise_for_status()
                payload = response.json()
                raw_urls = payload.get("packagesPerMonth") if isinstance(payload, dict) else None
                if not isinstance(raw_urls, list) or not raw_urls:
                    raise RuntimeError("PACKAGES_PER_MONTH_MISSING_OR_EMPTY")
                manifest = []
                for raw in raw_urls:
                    url_value = clean(raw)
                    month = month_tuple_from_url(url_value)
                    if not url_value or not month:
                        continue
                    path = urlsplit(url_value).path
                    manifest.append({
                        "month": month_key(month),
                        "month_tuple": month,
                        "publisher_url": url_value,
                        "path": path,
                    })
                if not manifest:
                    raise RuntimeError("NO_PARSEABLE_MONTH_PACKAGES")
                manifest.sort(key=lambda x: x["month_tuple"])
                selected_base = f"{urlsplit(response.url).scheme}://{urlsplit(response.url).netloc}"
                return selected_base, manifest, {"attempts": attempts, "list_url": response.url}
            except Exception as exc:
                last_error = exc
                if attempt + 1 < RETRIES:
                    time.sleep(min(12.0, 1.5 * (2**attempt)))
    raise RuntimeError(f"MALTA_EPPS_OCDS_MANIFEST_FAILED:{last_error!r}")


def select_manifest(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [x for x in manifest if x["month_tuple"] >= FIRST_MONTH]
    if MODE == "reconcile":
        return eligible
    cutoff = subtract_months(NOW.year, NOW.month, DELTA_MONTHS - 1)
    return [x for x in eligible if x["month_tuple"] >= cutoff]


def package_url(selected_base: str, item: dict[str, Any]) -> str:
    # Match OCP Kingfisher: keep the publisher-provided path but bind it to the
    # successfully probed official ePPS host, avoiding stale hostname aliases.
    return selected_base.rstrip("/") + "/" + str(item["path"]).lstrip("/")


def fetch_package(selected_base: str, item: dict[str, Any]) -> dict[str, Any]:
    url = package_url(selected_base, item)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/zip,application/octet-stream,*/*"})
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = session.get(url, timeout=180, allow_redirects=True)
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            archive = zipfile.ZipFile(io.BytesIO(response.content))
            records: list[dict[str, Any]] = []
            json_files = 0
            for name in archive.namelist():
                if name.endswith("/") or not name.lower().endswith(".json"):
                    continue
                json_files += 1
                payload = json.loads(archive.read(name).decode("utf-8-sig", errors="strict"))
                records.extend(iter_records(payload))
            if not json_files:
                raise RuntimeError("ZIP_HAS_NO_JSON_FILES")
            return {
                "month": item["month"],
                "url": response.url,
                "bytes": len(response.content),
                "zip_entries": len(archive.namelist()),
                "json_files": json_files,
                "records": records,
                "attempts": attempt + 1,
            }
        except Exception as exc:
            last_error = exc
            if attempt + 1 < RETRIES:
                time.sleep(min(20.0, 1.5 * (2**attempt)))
    raise RuntimeError(f"MALTA_EPPS_OCDS_PACKAGE_FAILED month={item['month']}: {last_error!r}")


def normalize_record(record: dict[str, Any], source_month: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    compiled = record.get("compiledRelease")
    if not isinstance(compiled, dict):
        return None, None
    candidate = release_to_candidate(
        compiled,
        source="MALTA_EPPS_OCDS",
        portal="MALTA_EPPS",
        notice_url=None,
        now=NOW,
    )
    if not candidate:
        return None, None

    status = clean(candidate.get("tender_status")).lower()
    deadline_raw = clean(candidate.get("deadline"))
    current = bool(
        deadline_raw
        and candidate.get("current") is True
        and status not in {"cancelled", "canceled", "complete", "withdrawn", "unsuccessful"}
    )
    candidate["current"] = current
    candidate["currentness_evidence"] = (
        "MALTA_EPPS_OCDS_FUTURE_TENDER_PERIOD_ENDDATE"
        if current
        else "MALTA_EPPS_OCDS_DEADLINE_EXPIRED_UNKNOWN_OR_TERMINAL"
    )
    candidate["source_package_month"] = source_month
    candidate["record_ocid"] = clean(record.get("ocid")) or candidate.get("ocid")
    route = dict(candidate.get("route") or {})
    route["ocds_record_package_month"] = source_month
    route["ocds_record_package_contract"] = "EUROPEAN_DYNAMICS_RECORD_PACKAGE"
    candidate["route"] = route

    radar = None
    if not deadline_raw and status in {"active", "planned"}:
        radar = dict(candidate)
        radar["current"] = False
        radar["currentness_evidence"] = "MALTA_EPPS_OCDS_ACTIVE_OR_PLANNED_WITHOUT_DEADLINE_RADAR_ONLY"
    return candidate, radar


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json,*/*"})
    errors: list[dict[str, Any]] = []
    try:
        selected_base, publisher_manifest, manifest_telemetry = discover_manifest(session)
    except Exception as exc:
        selected_base = None
        publisher_manifest = []
        manifest_telemetry = {}
        errors.append({"stage": "manifest", "error": repr(exc)})

    requested = select_manifest(publisher_manifest) if publisher_manifest else []
    package_telemetry: list[dict[str, Any]] = []
    latest_records: dict[str, tuple[dict[str, Any], str, tuple[str, str]]] = {}

    if selected_base and requested:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_package, selected_base, item): item for item in requested}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                    records = result.pop("records")
                    result["record_count"] = len(records)
                    package_telemetry.append(result)
                    for record in records:
                        compiled = record.get("compiledRelease") if isinstance(record.get("compiledRelease"), dict) else {}
                        ocid = clean(record.get("ocid") or compiled.get("ocid"))
                        if not ocid:
                            continue
                        version = record_version_key(record)
                        old = latest_records.get(ocid)
                        if old is None or version >= old[2]:
                            latest_records[ocid] = (record, item["month"], version)
                except Exception as exc:
                    errors.append({"month": item["month"], "error": repr(exc)})

    package_telemetry.sort(key=lambda x: x.get("month") or "")
    requested_months = [x["month"] for x in requested]
    completed_months = [x["month"] for x in package_telemetry]
    partitions_complete = bool(requested and not errors and completed_months == requested_months)

    rows: list[dict[str, Any]] = []
    radar: list[dict[str, Any]] = []
    normalization_drops = 0
    for record, source_month, _version in latest_records.values():
        candidate, radar_row = normalize_record(record, source_month)
        if not candidate:
            normalization_drops += 1
            continue
        rows.append(candidate)
        if radar_row:
            radar.append(radar_row)

    rows.sort(key=lambda x: (x.get("deadline") or "9999", x.get("candidate_id") or ""))
    current = [x for x in rows if x.get("current")]
    radar.sort(key=lambda x: (x.get("candidate_id") or ""))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)
    write_jsonl(OUT / "radar_unknown_deadline.jsonl", radar)

    offered_months = [x["month"] for x in publisher_manifest]
    latest_offered = offered_months[-1] if offered_months else None
    earliest_offered = offered_months[0] if offered_months else None
    current_month = f"{NOW.year:04d}-{NOW.month:02d}"
    previous = subtract_months(NOW.year, NOW.month, 1)
    previous_month = month_key(previous)
    manifest_fresh = bool(latest_offered and latest_offered >= previous_month)
    full_history = bool(
        MODE == "reconcile"
        and requested_months
        and requested_months == [x["month"] for x in publisher_manifest if x["month_tuple"] >= FIRST_MONTH]
        and requested_months[0] <= "2019-10"
    )
    exhaustive = bool(full_history and partitions_complete and manifest_fresh)

    stats = {
        "source": "MALTA_EPPS_OCDS",
        "portal": "MALTA_EPPS",
        "grain": "NOTICE_FIRST_TENDER",
        "listing_contract": "MALTA_EPPS_EUROPEAN_DYNAMICS_OCDS_RECORD_PACKAGES_V1",
        "reference_collector": "open-contracting/kingfisher-collect: malta + EuropeanDynamicsBase",
        "discovery_mode": MODE,
        "selected_official_base": selected_base,
        "manifest_list_path": LIST_PATH,
        "publisher_manifest_months": len(publisher_manifest),
        "earliest_offered_month": earliest_offered,
        "latest_offered_month": latest_offered,
        "current_month": current_month,
        "manifest_fresh_within_one_month": manifest_fresh,
        "packages_requested": len(requested_months),
        "packages_completed": len(completed_months),
        "requested_months": requested_months,
        "completed_months": completed_months,
        "record_ocids_latest": len(latest_records),
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "deadline_unknown_radar": len(radar),
        "normalization_drops": normalization_drops,
        "publication_partitions_complete": partitions_complete,
        "full_publication_history_requested": full_history,
        "enumeration_exhausted": exhaustive,
        "enumeration_complete": exhaustive,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": exhaustive and bool(current),
        "errors": errors,
        "warnings": ([] if exhaustive else [{
            "type": "MALTA_EPPS_OCDS_DELTA_STALE_OR_INCOMPLETE_HISTORY",
            "impact": "NO_FULL_LIVE_COVERAGE_CREDIT",
        }]),
        "manifest_telemetry": manifest_telemetry,
        "package_telemetry": package_telemetry,
        "generated_at": NOW.isoformat(),
        "semantics": (
            "Official Malta ePPS OCDS record-package service, following OCP Kingfisher's maintained EuropeanDynamicsBase contract. "
            "The publisher's packagesPerMonth manifest is authoritative for offered partitions. RECONCILE downloads every offered package from the maintained 2019-10 start through the freshest available month and exact-reconciles requested/completed packages before live coverage credit. "
            "Records are merged by OCID using the latest compiled record version. Current bid opportunities require a future tenderPeriod.endDate and non-terminal tender status; active/planned records with no deadline are preserved as radar only."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    if errors or not rows:
        raise SystemExit(3 if errors else 2)
    if MODE == "reconcile" and not exhaustive:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
