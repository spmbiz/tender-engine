from __future__ import annotations

import io
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

try:
    from pipeline.ocds_release_normalizer import release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_to_candidate

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/DE_DOE"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://oeffentlichevergabe.de/api/notice-exports"
UA = "Tender-Engine/7.1 (+official Germany Bekanntmachungsservice OpenData OCDS)"
MODE = os.getenv("DISCOVERY_MODE", "delta").strip().lower()
WORKERS = max(1, min(6, int(os.getenv("DE_DOE_WORKERS", "4"))))
RETRIES = max(1, min(8, int(os.getenv("DE_DOE_RETRIES", "5"))))
DELTA_MONTHS = max(1, min(12, int(os.getenv("DE_DOE_DELTA_MONTHS", "3"))))
FIRST_FULL_MONTH = (2022, 12)
NOW = datetime.now(timezone.utc)


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def add_month(year: int, month: int, delta: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + delta
    return absolute // 12, absolute % 12 + 1


def full_month_manifest(now: datetime) -> list[str]:
    y, m = FIRST_FULL_MONTH
    out: list[str] = []
    while (y, m) <= (now.year, now.month):
        out.append(month_key(y, m))
        y, m = add_month(y, m, 1)
    return out


def delta_month_manifest(now: datetime) -> list[str]:
    out: list[str] = []
    for offset in range(DELTA_MONTHS - 1, -1, -1):
        y, m = add_month(now.year, now.month, -offset)
        if (y, m) >= FIRST_FULL_MONTH:
            out.append(month_key(y, m))
    return out


def iter_releases(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        releases = value.get("releases")
        if isinstance(releases, list):
            for release in releases:
                if isinstance(release, dict):
                    yield release
            return
        if value.get("ocid") and isinstance(value.get("tender"), dict):
            yield value
            return
    elif isinstance(value, list):
        for item in value:
            yield from iter_releases(item)


def fetch_month(month: str) -> dict[str, Any]:
    headers = {
        "User-Agent": UA,
        "Accept": "application/vnd.bekanntmachungsservice.ocds.zip+zip, application/zip;q=0.9, */*;q=0.2",
    }
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = requests.get(
                URL,
                params={"pubMonth": month, "format": "ocds.zip"},
                headers=headers,
                timeout=180,
            )
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            content = response.content
            archive = zipfile.ZipFile(io.BytesIO(content))
            releases: list[dict[str, Any]] = []
            json_files = 0
            parse_errors: list[dict[str, Any]] = []
            for name in archive.namelist():
                if name.endswith("/") or not name.lower().endswith(".json"):
                    continue
                json_files += 1
                try:
                    payload = json.loads(archive.read(name).decode("utf-8-sig", errors="strict"))
                    releases.extend(iter_releases(payload))
                except Exception as exc:
                    parse_errors.append({"file": name, "error": repr(exc)})
            if parse_errors:
                raise RuntimeError(f"MONTH_JSON_PARSE_ERRORS:{month}:{parse_errors[:3]!r}")
            return {
                "month": month,
                "status": response.status_code,
                "bytes": len(content),
                "zip_files": len(archive.namelist()),
                "json_files": json_files,
                "releases": releases,
                "attempts": attempt + 1,
            }
        except Exception as exc:
            last_error = exc
            if attempt + 1 < RETRIES:
                time.sleep(min(20.0, 1.5 * (2**attempt)))
    raise RuntimeError(f"DE_DOE_MONTH_FAILED month={month}: {last_error!r}")


def publication_identity(release: dict[str, Any]) -> str:
    rid = clean(release.get("id"))
    if rid:
        return rid
    ocid = clean(release.get("ocid"))
    date = clean(release.get("date"))
    return f"{ocid}|{date}" if ocid or date else json.dumps(release, sort_keys=True, ensure_ascii=False)


def normalize(release: dict[str, Any], month: str) -> dict[str, Any] | None:
    rid = clean(release.get("id"))
    notice_url = f"https://oeffentlichevergabe.de/ui/de/notices/{rid}" if rid else None
    candidate = release_to_candidate(
        release,
        source="DE_DOE",
        portal="DE_BEKANNTMACHUNGSSERVICE",
        notice_url=notice_url,
        now=NOW,
    )
    if not candidate:
        return None

    status = clean(candidate.get("tender_status")).lower()
    deadline = clean(candidate.get("deadline"))
    # Current contract-opportunity semantics are deliberately stricter than the
    # shared generic normalizer: planning/PIN releases without a submission
    # deadline remain radar, not live bid opportunities.
    current = bool(candidate.get("current")) and (bool(deadline) or status == "active")
    candidate["current"] = current
    candidate["currentness_evidence"] = (
        "DE_OFFICIAL_OCDS_FUTURE_DEADLINE_OR_ACTIVE_TENDER_STATUS"
        if current
        else "DE_OFFICIAL_OCDS_NOT_PROVEN_CURRENT_COMPETITION"
    )
    candidate["source_publication_month"] = month
    candidate["source_contract"] = "GERMANY_BEKANNTMACHUNGSSERVICE_MONTHLY_OCDS"
    return candidate


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    months = full_month_manifest(NOW) if MODE == "reconcile" else delta_month_manifest(NOW)
    expected = len(months)
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    release_by_identity: dict[str, tuple[dict[str, Any], str]] = {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        future_map = {pool.submit(fetch_month, month): month for month in months}
        for future in as_completed(future_map):
            month = future_map[future]
            try:
                result = future.result()
                releases = result.pop("releases")
                result["release_count"] = len(releases)
                telemetry.append(result)
                for release in releases:
                    identity = publication_identity(release)
                    # The same publication should not normally cross month
                    # partitions, but deterministic overwrite keeps reruns stable.
                    release_by_identity[identity] = (release, month)
            except Exception as exc:
                errors.append({"month": month, "error": repr(exc)})

    telemetry.sort(key=lambda x: x.get("month") or "")
    completed_months = sorted(x.get("month") for x in telemetry if x.get("status") == 200)
    publication_window_complete = not errors and completed_months == months

    records: dict[str, dict[str, Any]] = {}
    normalization_drops = 0
    for release, month in release_by_identity.values():
        candidate = normalize(release, month)
        if not candidate:
            normalization_drops += 1
            continue
        cid = clean(candidate.get("candidate_id"))
        if not cid:
            normalization_drops += 1
            continue
        existing = records.get(cid)
        if not existing or clean(candidate.get("published")) >= clean(existing.get("published")):
            records[cid] = candidate

    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x.get("candidate_id") or ""))
    current = [row for row in rows if row.get("current")]
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)

    full_manifest = MODE == "reconcile" and months == full_month_manifest(NOW)
    exhaustive = bool(full_manifest and publication_window_complete)
    stats = {
        "source": "DE_DOE",
        "portal": "DE_BEKANNTMACHUNGSSERVICE",
        "grain": "NOTICE_FIRST_TENDER",
        "listing_contract": "DE_DOE_OFFICIAL_MONTHLY_OCDS_V1",
        "discovery_mode": MODE,
        "first_official_month": "2022-12",
        "last_requested_month": months[-1] if months else None,
        "months_requested": expected,
        "months_completed": len(completed_months),
        "month_manifest": months,
        "completed_months": completed_months,
        "source_releases_seen": len(release_by_identity),
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "normalization_drops": normalization_drops,
        "publication_window_enumeration_complete": publication_window_complete,
        "full_publication_history_requested": full_manifest,
        "enumeration_exhausted": exhaustive,
        "enumeration_complete": exhaustive,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": exhaustive and bool(current),
        "errors": errors,
        "warnings": ([] if exhaustive else [{
            "type": "DE_DELTA_WINDOW_NOT_FULL_HISTORY" if MODE != "reconcile" else "DE_FULL_HISTORY_INCOMPLETE",
            "impact": "NO_FULL_LIVE_COVERAGE_CREDIT",
        }]),
        "telemetry": telemetry,
        "generated_at": NOW.isoformat(),
        "source_url": URL,
        "semantics": (
            "Official German Bekanntmachungsservice OpenData monthly OCDS only. "
            "RECONCILE enumerates every official publication month from 2022-12 through the current month and grants live coverage credit only when every month succeeds. "
            "DELTA intentionally reads only recent months for freshness and cannot claim exhaustive live coverage by itself. "
            "Current bid opportunities require a future parsed tender deadline or official OCDS active tender status; planning-only rows remain non-current radar."
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
