from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from pipeline.ocds_release_normalizer import release_awards, release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_awards, release_to_candidate

BASE = "https://ocds-api.etenders.gov.za/api/OCDSReleases"
UA = "Tender-Engine/6.6 (+public procurement research; South Africa National Treasury OCDS; adaptive windows)"


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_page(session: requests.Session, *, page: int, size: int, start: date, end: date) -> dict[str, Any]:
    params = {
        "PageNumber": page,
        "PageSize": size,
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
    }
    last = None
    for attempt in range(5):
        try:
            r = session.get(BASE, params=params, timeout=90)
            if r.status_code >= 500:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("NON_OBJECT_JSON")
            return data
        except Exception as exc:
            last = exc
            if attempt < 4:
                time.sleep(min(10, 1.5 * (2 ** attempt)))
    raise RuntimeError(f"ZA_PAGE_FAILED page={page} size={size} {start}..{end}: {last!r}")


def consume_release(release: dict[str, Any], *, now: datetime, candidates: dict, awards: list):
    ocid = str(release.get("ocid") or "").strip()
    notice_url = f"{BASE}/release/{ocid}" if ocid else None
    cand = release_to_candidate(
        release,
        source="ZA_ETENDERS_OCDS",
        portal="ZA_ETENDERS",
        notice_url=notice_url,
        now=now,
    )
    if cand:
        candidates[cand["candidate_id"]] = cand
    awards.extend(
        release_awards(
            release,
            source="ZA_ETENDERS_OCDS",
            portal="ZA_ETENDERS",
            notice_url=notice_url,
        )
    )


def harvest_window(session, *, start: date, end: date, page_size: int, now: datetime,
                   candidates: dict, awards: list, telemetry: list, depth: int = 0) -> bool:
    """Harvest one inclusive release-date window.

    National Treasury's API intermittently returns HTTP 500 on later pages of broad
    windows. Instead of losing the country, bisect the release-date window and retry.
    This preserves the official API as truth and never fabricates missing pages.
    """
    local_pages = []
    try:
        page = 1
        while True:
            pkg = get_page(session, page=page, size=page_size, start=start, end=end)
            releases = pkg.get("releases") or []
            if not isinstance(releases, list):
                raise RuntimeError("RELEASES_NOT_LIST")
            links = pkg.get("links") or {}
            next_url = links.get("next") if isinstance(links, dict) else None
            local_pages.append({"page": page, "releases": len(releases), "next": bool(next_url)})
            for release in releases:
                if isinstance(release, dict):
                    consume_release(release, now=now, candidates=candidates, awards=awards)
            if not next_url or not releases:
                telemetry.append({
                    "start": start.isoformat(), "end": end.isoformat(), "depth": depth,
                    "status": "COMPLETE", "pages": local_pages,
                })
                return True
            page += 1
    except Exception as exc:
        if start < end:
            span = (end - start).days
            mid = start + timedelta(days=span // 2)
            telemetry.append({
                "start": start.isoformat(), "end": end.isoformat(), "depth": depth,
                "status": "BISECT", "failed_after_pages": local_pages, "error": repr(exc),
                "left": [start.isoformat(), mid.isoformat()],
                "right": [(mid + timedelta(days=1)).isoformat(), end.isoformat()],
            })
            left_ok = harvest_window(
                session, start=start, end=mid, page_size=page_size, now=now,
                candidates=candidates, awards=awards, telemetry=telemetry, depth=depth + 1,
            )
            right_ok = harvest_window(
                session, start=mid + timedelta(days=1), end=end, page_size=page_size, now=now,
                candidates=candidates, awards=awards, telemetry=telemetry, depth=depth + 1,
            )
            return left_ok and right_ok

        # Single-day failures get one final smaller-page attempt. This handles a
        # pathological day with >page_size releases without expanding the date range.
        if page_size > 20:
            smaller = max(20, page_size // 2)
            telemetry.append({
                "start": start.isoformat(), "end": end.isoformat(), "depth": depth,
                "status": "REDUCE_PAGE_SIZE", "from": page_size, "to": smaller,
                "error": repr(exc),
            })
            return harvest_window(
                session, start=start, end=end, page_size=smaller, now=now,
                candidates=candidates, awards=awards, telemetry=telemetry, depth=depth + 1,
            )

        telemetry.append({
            "start": start.isoformat(), "end": end.isoformat(), "depth": depth,
            "status": "FAILED_SINGLE_DAY", "error": repr(exc),
        })
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/ZA_ETENDERS_OCDS")))
    ap.add_argument("--lookback-days", type=int, default=int(os.getenv("ZA_LOOKBACK_DAYS", "90")))
    ap.add_argument("--window-days", type=int, default=int(os.getenv("ZA_WINDOW_DAYS", "14")))
    ap.add_argument("--page-size", type=int, default=int(os.getenv("ZA_PAGE_SIZE", "100")))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    first = (now - timedelta(days=max(1, args.lookback_days))).date()
    last = now.date()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    candidates: dict[str, dict[str, Any]] = {}
    awards: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    cursor = first
    step = max(1, args.window_days)
    all_complete = True
    while cursor <= last:
        end = min(last, cursor + timedelta(days=step - 1))
        ok = harvest_window(
            session, start=cursor, end=end, page_size=max(20, args.page_size), now=now,
            candidates=candidates, awards=awards, telemetry=telemetry,
        )
        all_complete = all_complete and ok
        cursor = end + timedelta(days=1)

    if not all_complete:
        errors.append({"type": "ONE_OR_MORE_ZA_WINDOWS_INCOMPLETE"})

    raw = sorted(candidates.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in raw if x.get("current")]
    write_jsonl(out / "raw.jsonl", raw)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "awards.jsonl", awards)
    stats = {
        "source": "ZA_ETENDERS_OCDS",
        "grain": ["NOTICE_FIRST_TENDER", "AWARD"],
        "listing_contract": "ZA_ETENDERS_OCDS_ADAPTIVE_RELEASE_WINDOWS_V2",
        "date_from": first.isoformat(),
        "date_to": last.isoformat(),
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "awards_materialized": len(awards),
        "document_routes": sum(bool((x.get("route") or {}).get("document_urls")) for x in raw),
        "competition_signal_rows": sum(x.get("tenderers_received_observed") is not None for x in raw)
        + sum(x.get("tenderers_received_observed") is not None for x in awards),
        "publication_window_enumeration_complete": all_complete,
        "enumeration_complete": all_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": all_complete and bool(current),
        "generated_at": now.isoformat(),
        "errors": errors,
        "telemetry": telemetry,
        "source_url": BASE,
        "semantics": (
            "Official National Treasury OCDS release API only. Broad release-date windows are split recursively on "
            "server/pagination failures, following the same small-period collection principle used by mature OCDS "
            "collectors. Coverage is credited only when every date partition is exhausted without an unresolved day."
        ),
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not all_complete or (not raw and not awards):
        raise SystemExit(3 if not all_complete else 2)


if __name__ == "__main__":
    main()
