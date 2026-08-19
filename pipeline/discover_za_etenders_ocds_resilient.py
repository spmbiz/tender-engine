from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

try:
    from pipeline.ocds_release_normalizer import release_awards, release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_awards, release_to_candidate

BASE = "https://ocds-api.etenders.gov.za/api/OCDSReleases"
OFFICIAL_HOST = "ocds-api.etenders.gov.za"
UA = "Tender-Engine/7.0 (+official South Africa National Treasury OCDS; Kingfisher-compatible pagination)"


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_package(session: requests.Session, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch one official OCDS release package with bounded retries.

    Kingfisher's National Treasury spider follows the publisher-provided
    ``links.next`` URL verbatim. We do the same: only the first request is
    synthesized from dateFrom/dateTo/PageNumber=1. Later pages are never
    reconstructed locally.
    """
    last = None
    for attempt in range(4):
        try:
            r = session.get(url, params=params, timeout=45)
            if r.status_code >= 500 or r.status_code in (408, 425, 429):
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("NON_OBJECT_JSON")
            return data
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(1.5 * (2 ** attempt))
    raise RuntimeError(f"ZA_PACKAGE_FAILED url={url!r} params={params!r}: {last!r}")


def normalize_next_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(BASE, value.strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != OFFICIAL_HOST:
        raise RuntimeError(f"ZA_NEXT_LINK_LEFT_OFFICIAL_HOST:{url}")
    return url


def award_key(row: dict[str, Any]) -> tuple:
    return (
        row.get("ocid"),
        row.get("award_id"),
        row.get("supplier_id"),
        row.get("supplier_name"),
        row.get("source_release_hash"),
    )


def consume_release(release: dict[str, Any], *, now: datetime, candidates: dict, awards: dict):
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
    for row in release_awards(
        release,
        source="ZA_ETENDERS_OCDS",
        portal="ZA_ETENDERS",
        notice_url=notice_url,
    ):
        awards[award_key(row)] = row


def harvest_window(
    session,
    *,
    start: date,
    end: date,
    now: datetime,
    candidates: dict,
    awards: dict,
    telemetry: list,
    depth: int = 0,
    halo_depth: int = 0,
) -> bool:
    """Harvest one inclusive release-date window.

    Primary strategy mirrors Open Contracting Partnership's maintained
    ``south_africa_national_treasury_api`` Kingfisher spider:
    - seven-day periods;
    - one request stream;
    - first URL uses dateFrom/dateTo/PageNumber=1;
    - every later page follows the official OCDS ``links.next`` URL.

    If a multi-day period fails after retries, it is bisected. If one exact day
    itself returns a publisher-side 5xx, we make one *official overlapping halo*
    attempt that includes an adjacent healthy day. Exhausting that wider official
    interval proves coverage of the broken day too; extra releases are harmlessly
    exact-deduped by candidate/award identity. The halo is attempted once only and
    can never recursively claim success from an unresolved child partition.
    """
    local_pages = []
    try:
        url = BASE
        params: dict[str, Any] | None = {
            "dateFrom": start.isoformat(),
            "dateTo": end.isoformat(),
            "PageNumber": 1,
        }
        seen_urls = set()
        page_no = 1
        while True:
            request_identity = url if params is None else f"{url}?dateFrom={start}&dateTo={end}&PageNumber=1"
            if request_identity in seen_urls:
                raise RuntimeError(f"ZA_REPEATED_NEXT_LINK:{request_identity}")
            seen_urls.add(request_identity)

            pkg = fetch_package(session, url, params=params)
            releases = pkg.get("releases") or []
            if not isinstance(releases, list):
                raise RuntimeError("RELEASES_NOT_LIST")
            links = pkg.get("links") or {}
            raw_next = links.get("next") if isinstance(links, dict) else None
            next_url = normalize_next_url(raw_next)
            local_pages.append({
                "page": page_no,
                "releases": len(releases),
                "next": bool(next_url),
                "request_mode": "SYNTHESIZED_FIRST_PAGE" if params is not None else "OFFICIAL_LINKS_NEXT",
            })
            for release in releases:
                if isinstance(release, dict):
                    consume_release(release, now=now, candidates=candidates, awards=awards)

            if not next_url:
                telemetry.append({
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "depth": depth,
                    "halo_depth": halo_depth,
                    "status": "COMPLETE",
                    "pages": local_pages,
                    "pagination_contract": "OFFICIAL_LINKS_NEXT",
                })
                return True

            url = next_url
            params = None
            page_no += 1
    except Exception as exc:
        if start < end:
            span = (end - start).days
            mid = start + timedelta(days=span // 2)
            telemetry.append({
                "start": start.isoformat(),
                "end": end.isoformat(),
                "depth": depth,
                "halo_depth": halo_depth,
                "status": "BISECT",
                "failed_after_pages": local_pages,
                "error": repr(exc),
                "left": [start.isoformat(), mid.isoformat()],
                "right": [(mid + timedelta(days=1)).isoformat(), end.isoformat()],
            })
            left_ok = harvest_window(
                session,
                start=start,
                end=mid,
                now=now,
                candidates=candidates,
                awards=awards,
                telemetry=telemetry,
                depth=depth + 1,
                halo_depth=halo_depth,
            )
            right_ok = harvest_window(
                session,
                start=mid + timedelta(days=1),
                end=end,
                now=now,
                candidates=candidates,
                awards=awards,
                telemetry=telemetry,
                depth=depth + 1,
                halo_depth=halo_depth,
            )
            return left_ok and right_ok

        # Some National Treasury dates are reproducibly broken as an exact
        # one-day query even though a wider official interval containing that day
        # can be enumerated. Try one adjacent-day halo, but never recurse halos.
        if halo_depth == 0:
            today = now.date()
            if end < today:
                halo_start, halo_end = start, min(today, end + timedelta(days=1))
            else:
                halo_start, halo_end = max(date(2017, 1, 1), start - timedelta(days=1)), end
            if halo_start < halo_end:
                telemetry.append({
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "depth": depth,
                    "halo_depth": halo_depth,
                    "status": "HALO_RECOVERY_ATTEMPT",
                    "error": repr(exc),
                    "failed_after_pages": local_pages,
                    "halo": [halo_start.isoformat(), halo_end.isoformat()],
                })
                halo_ok = harvest_window(
                    session,
                    start=halo_start,
                    end=halo_end,
                    now=now,
                    candidates=candidates,
                    awards=awards,
                    telemetry=telemetry,
                    depth=depth + 1,
                    halo_depth=1,
                )
                telemetry.append({
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "depth": depth,
                    "halo_depth": halo_depth,
                    "status": "HALO_RECOVERY_COMPLETE" if halo_ok else "HALO_RECOVERY_FAILED",
                    "halo": [halo_start.isoformat(), halo_end.isoformat()],
                })
                if halo_ok:
                    return True

        telemetry.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "depth": depth,
            "halo_depth": halo_depth,
            "status": "FAILED_SINGLE_DAY",
            "error": repr(exc),
            "failed_after_pages": local_pages,
        })
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/ZA_ETENDERS_OCDS")))
    ap.add_argument("--lookback-days", type=int, default=int(os.getenv("ZA_LOOKBACK_DAYS", "90")))
    ap.add_argument("--window-days", type=int, default=int(os.getenv("ZA_WINDOW_DAYS", "7")))
    ap.add_argument("--page-size", type=int, default=int(os.getenv("ZA_PAGE_SIZE", "0")))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    first = (now - timedelta(days=max(1, args.lookback_days))).date()
    last = now.date()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    candidates: dict[str, dict[str, Any]] = {}
    awards: dict[tuple, dict[str, Any]] = {}
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    cursor = first
    step = max(1, args.window_days)
    all_complete = True
    while cursor <= last:
        end = min(last, cursor + timedelta(days=step - 1))
        ok = harvest_window(
            session,
            start=cursor,
            end=end,
            now=now,
            candidates=candidates,
            awards=awards,
            telemetry=telemetry,
        )
        all_complete = all_complete and ok
        cursor = end + timedelta(days=1)

    if not all_complete:
        errors.append({"type": "ONE_OR_MORE_ZA_WINDOWS_INCOMPLETE"})

    raw = sorted(candidates.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in raw if x.get("current")]
    award_rows = list(awards.values())
    write_jsonl(out / "raw.jsonl", raw)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "awards.jsonl", award_rows)
    stats = {
        "source": "ZA_ETENDERS_OCDS",
        "grain": ["NOTICE_FIRST_TENDER", "AWARD"],
        "listing_contract": "ZA_ETENDERS_OCDS_KINGFISHER_LINKS_NEXT_V4_HALO_RECOVERY",
        "reference_collector": "open-contracting/kingfisher-collect: south_africa_national_treasury_api + LinksSpider",
        "date_from": first.isoformat(),
        "date_to": last.isoformat(),
        "window_days": step,
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "awards_materialized": len(award_rows),
        "document_routes": sum(bool((x.get("route") or {}).get("document_urls")) for x in raw),
        "competition_signal_rows": sum(x.get("tenderers_received_observed") is not None for x in raw)
        + sum(x.get("tenderers_received_observed") is not None for x in award_rows),
        "halo_recoveries": sum(1 for x in telemetry if x.get("status") == "HALO_RECOVERY_COMPLETE"),
        "halo_failures": sum(1 for x in telemetry if x.get("status") == "HALO_RECOVERY_FAILED"),
        "publication_window_enumeration_complete": all_complete,
        "enumeration_complete": all_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": all_complete and bool(current),
        "generated_at": now.isoformat(),
        "errors": errors,
        "telemetry": telemetry,
        "source_url": BASE,
        "semantics": (
            "Official National Treasury OCDS API only. Collection mirrors OCP Kingfisher's seven-day periodic spider and follows "
            "publisher-provided links.next verbatim. Multi-day failures are bisected. A publisher-broken exact day may be covered "
            "once by an overlapping adjacent-day official interval; coverage credit is granted only if that halo itself exhausts "
            "without an unresolved child. Candidate and award duplicates are removed by deterministic identities."
        ),
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not all_complete or (not raw and not award_rows):
        raise SystemExit(3 if not all_complete else 2)


if __name__ == "__main__":
    main()
