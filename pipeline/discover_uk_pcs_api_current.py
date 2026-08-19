from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from pipeline.ocds_release_normalizer import release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_to_candidate

BASE = "https://api.publiccontractsscotland.gov.uk/v1"
NOTICES_URL = BASE + "/Notices"
NOTICE_URL = BASE + "/Notice"
NOW = datetime.now(timezone.utc)
UA = "Tender-Engine/PCS-OCDS/1.0 (+official Public Contracts Scotland API; Kingfisher collection pattern)"

# Public Contracts Scotland API notice types which can represent a live buying
# opportunity. Award/result/VEAT/modification-only forms are intentionally not
# used to seed the live opportunity set. Type 102 is the PCS website Contract
# Notice. This mirrors the monthly/type request pattern used by OCP Kingfisher.
OPPORTUNITY_NOTICE_TYPES = [2, 5, 7, 12, 21, 22, 23, 24, 102]


def month_start(year: int, month: int) -> tuple[int, int]:
    return year, month


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def months_back(count: int) -> list[str]:
    y, m = NOW.year, NOW.month
    out = []
    for _ in range(max(1, count)):
        out.append(f"{m:02d}-{y:04d}")
        y, m = previous_month(y, m)
    return out


def months_from_2019() -> list[str]:
    y, m = 2019, 1
    out = []
    while (y, m) <= (NOW.year, NOW.month):
        out.append(f"{m:02d}-{y:04d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def fetch_one(month: str, notice_type: int, retries: int = 5) -> dict[str, Any]:
    params = {"dateFrom": month, "noticeType": notice_type, "outputType": 0}
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(
                NOTICES_URL,
                params=params,
                timeout=90,
                headers={"User-Agent": UA, "Accept": "application/json"},
            )
            if r.status_code >= 500:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("PCS API returned non-object JSON")
            releases = data.get("releases")
            if releases is None:
                releases = []
            if not isinstance(releases, list):
                raise RuntimeError("PCS API releases is not a list")
            return {
                "month": month,
                "notice_type": notice_type,
                "status": r.status_code,
                "releases": releases,
                "package_uri": data.get("uri"),
            }
        except Exception as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(min(12, 1.5 * (2 ** attempt)))
    raise RuntimeError(f"PCS_API_FAILED month={month} notice_type={notice_type}: {last!r}")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/UK_PCS_OCDS")))
    ap.add_argument("--months", type=int, default=int(os.getenv("PCS_API_LOOKBACK_MONTHS", "36")))
    ap.add_argument("--workers", type=int, default=int(os.getenv("PCS_API_WORKERS", "4")))
    ap.add_argument("--from-2019", action="store_true", default=os.getenv("DISCOVERY_MODE") == "reconcile")
    args = ap.parse_args()

    months = months_from_2019() if args.from_2019 else months_back(args.months)
    tasks = [(month, notice_type) for month in months for notice_type in OPPORTUNITY_NOTICE_TYPES]
    telemetry = []
    errors = []
    releases_seen = 0
    candidates: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        futures = {pool.submit(fetch_one, month, nt): (month, nt) for month, nt in tasks}
        for future in as_completed(futures):
            month, nt = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                errors.append({"month": month, "notice_type": nt, "error": repr(exc)})
                continue
            releases = result["releases"]
            releases_seen += len(releases)
            telemetry.append({
                "month": month,
                "notice_type": nt,
                "http_status": result["status"],
                "releases": len(releases),
            })
            for release in releases:
                if not isinstance(release, dict):
                    continue
                ocid = str(release.get("ocid") or "").strip()
                notice_url = f"{NOTICE_URL}?id={ocid}" if ocid else NOTICES_URL
                cand = release_to_candidate(
                    release,
                    source="UK_PCS_OCDS",
                    portal="PUBLIC_CONTRACTS_SCOTLAND",
                    notice_url=notice_url,
                    now=NOW,
                )
                if not cand or not cand.get("current"):
                    continue
                # A planned record without a deadline is useful as procurement
                # intelligence, but it is not equivalent to PCS Current Opportunity.
                # Keep it out of this strict live lane unless the tender is active
                # or has a future tenderPeriod endDate.
                status = str(cand.get("tender_status") or "").lower()
                if not cand.get("deadline") and status != "active":
                    continue
                cand["country"] = "GB"
                cand["currentness_evidence"] = "PCS_OFFICIAL_OCDS_API_FUTURE_DEADLINE_OR_ACTIVE_TENDER"
                cand["route"]["pcs_api_month"] = month
                cand["route"]["pcs_notice_type"] = nt
                candidates[cand["candidate_id"]] = cand

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    rows = sorted(candidates.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    write_jsonl(out / "raw.jsonl", rows)
    write_jsonl(out / "current.jsonl", rows)

    publication_complete = not errors and len(telemetry) == len(tasks)
    stats = {
        "source": "UK_PCS_OCDS",
        "portal": "PUBLIC_CONTRACTS_SCOTLAND",
        "listing_contract": "PCS_OFFICIAL_OCDS_MONTH_TYPE_V1_KINGFISHER_PATTERN",
        "collector_pattern_source": "open-contracting/kingfisher-collect: united_kingdom_scotland + ProactisBase",
        "api_url": NOTICES_URL,
        "months_requested": len(months),
        "notice_types": OPPORTUNITY_NOTICE_TYPES,
        "requests_expected": len(tasks),
        "requests_completed": len(telemetry),
        "source_releases_seen": releases_seen,
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "publication_window_enumeration_complete": publication_complete,
        "enumeration_exhausted": False,
        "enumeration_complete": False,
        "live_candidate_capable": bool(rows),
        "live_coverage_credit_allowed": False,
        "errors": errors,
        "warnings": [] if args.from_2019 else [{
            "type": "BOUNDED_MONTHLY_API_RECONSTRUCTION",
            "months": len(months),
            "coverage_credit": False,
        }],
        "telemetry": sorted(telemetry, key=lambda x: (x["month"], x["notice_type"])),
        "generated_at": NOW.isoformat(),
        "semantics": (
            "Official PCS OCDS API only. Requests follow the same month x noticeType pattern used by Open Contracting "
            "Partnership Kingfisher Collect. This eliminates fragile ASP.NET search pagination. Current candidates require "
            "a future tenderPeriod deadline or tender.status=active. Full PCS current-registry coverage remains fail-closed "
            "until the reconstructed active set is independently reconciled against the portal's Current Opportunity universe."
        ),
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not publication_complete or not rows:
        raise SystemExit(3 if errors else 2)


if __name__ == "__main__":
    main()
