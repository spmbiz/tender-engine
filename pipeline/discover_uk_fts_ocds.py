from __future__ import annotations

"""UK Find a Tender Service (FTS) OCDS discovery.

Official public release-package API. The three procurement stages are harvested
independently so awards/planning cannot consume the pagination budget for live
tenders. Cursor links are opaque and followed verbatim.
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from pipeline.ocds_release_normalizer import release_awards, release_to_candidate
except ModuleNotFoundError:  # direct `python pipeline/foo.py` execution
    from ocds_release_normalizer import release_awards, release_to_candidate

BASE = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
API_PROCESS = "https://www.find-tender.service.gov.uk/api/1.0/ocdsRecordPackages/{ocid}"
UA = "Tender-Engine/5.6 (+public procurement research; UK Find a Tender public OCDS API)"
STAGES = ("tender", "planning", "award")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def iso_seconds(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat(timespec="seconds")


def get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None, retries: int = 7) -> tuple[dict[str, Any], dict[str, Any]]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code in {429, 503}:
                try:
                    retry_after = max(1, min(120, int(r.headers.get("Retry-After", "5"))))
                except Exception:
                    retry_after = 5
                if attempt + 1 < retries:
                    time.sleep(retry_after)
                    continue
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("FTS returned non-object JSON")
            return data, {
                "status": r.status_code,
                "url": r.url,
                "remaining": r.headers.get("X-RateLimit-Remaining"),
            }
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(20, 2 ** attempt))
    raise RuntimeError(f"FTS request failed for {url}: {last!r}")


def harvest_stage(
    session: requests.Session,
    *,
    stage: str,
    updated_from: str,
    updated_to: str,
    page_limit: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    url: str | None = BASE
    params: dict[str, Any] | None = {
        "limit": page_limit,
        "updatedFrom": updated_from,
        "updatedTo": updated_to,
        "stages": stage,
    }
    seen_urls: set[str] = set()

    for page in range(max(1, max_pages)):
        if not url or url in seen_urls:
            if url in seen_urls:
                errors.append({"stage": stage, "page": page, "error": "REPEATED_NEXT_URL", "url": url})
            break
        seen_urls.add(url)
        try:
            pkg, meta = get_json(session, url, params=params)
        except Exception as exc:
            errors.append({"stage": stage, "page": page, "error": repr(exc), "url": url})
            break
        releases = pkg.get("releases") or []
        if not isinstance(releases, list):
            errors.append({"stage": stage, "page": page, "error": "RELEASES_NOT_LIST"})
            break
        links = pkg.get("links")
        nxt = links.get("next") if isinstance(links, dict) else None
        telemetry.append({
            "stage": stage,
            "page": page + 1,
            "releases": len(releases),
            "has_next": bool(isinstance(nxt, str) and nxt),
            "request_url": meta.get("url"),
        })
        for release in releases:
            if isinstance(release, dict):
                rows.append(release)
        # FTS documentation defines cursor pagination, and live implementations
        # expose the opaque next URL. Do not reconstruct the cursor.
        url = nxt if isinstance(nxt, str) and nxt else None
        params = None
        if not url:
            break
    else:
        if url:
            errors.append({"stage": stage, "error": "TRUNCATED_BY_PAGE_CAP", "max_pages": max_pages})

    return rows, telemetry, errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/UK_FTS_OCDS")))
    ap.add_argument("--lookback-days", type=int, default=int(os.getenv("FTS_LOOKBACK_DAYS", "5")))
    ap.add_argument("--max-pages", type=int, default=int(os.getenv("FTS_MAX_PAGES", "80")), help="Maximum pages independently for each stage.")
    ap.add_argument("--page-size", type=int, default=int(os.getenv("FTS_PAGE_SIZE", "100")))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    updated_from = iso_seconds(now - timedelta(days=max(1, args.lookback_days)))
    updated_to = iso_seconds(now + timedelta(minutes=5))
    page_size = max(1, min(100, args.page_size))
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    candidates: dict[str, dict[str, Any]] = {}
    pre_by_id: dict[str, dict[str, Any]] = {}
    award_rows: dict[str, dict[str, Any]] = {}
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    releases_by_stage: dict[str, int] = {}

    for stage in STAGES:
        releases, stage_telemetry, stage_errors = harvest_stage(
            session,
            stage=stage,
            updated_from=updated_from,
            updated_to=updated_to,
            page_limit=page_size,
            max_pages=max(1, args.max_pages),
        )
        releases_by_stage[stage] = len(releases)
        telemetry.extend(stage_telemetry)
        errors.extend(stage_errors)
        for release in releases:
            ocid = str(release.get("ocid") or "").strip()
            notice_url = API_PROCESS.format(ocid=ocid) if ocid else BASE
            if stage == "tender":
                cand = release_to_candidate(
                    release,
                    source="UK_FTS_OCDS",
                    portal="UK_FIND_A_TENDER",
                    notice_url=notice_url,
                    now=now,
                )
                if cand:
                    candidates[cand["candidate_id"]] = cand
            elif stage == "planning":
                cand = release_to_candidate(
                    release,
                    source="UK_FTS_OCDS",
                    portal="UK_FIND_A_TENDER",
                    notice_url=notice_url,
                    now=now,
                )
                if cand:
                    cand["grain"] = "PRE_TENDER_RADAR"
                    cand["current"] = True
                    pre_by_id[cand["candidate_id"]] = cand
            else:
                awards = release_awards(
                    release,
                    source="UK_FTS_OCDS",
                    portal="UK_FIND_A_TENDER",
                    notice_url=notice_url,
                )
                if awards:
                    for award in awards:
                        key = f"{award.get('ocid')}:{award.get('award_id')}:{award.get('supplier_id')}"
                        award_rows[key] = award
                else:
                    rid = str(release.get("id") or ocid or "").strip()
                    award_rows[f"notice:{rid}"] = {
                        "grain": "AWARD_NOTICE",
                        "source": "UK_FTS_OCDS",
                        "portal": "UK_FIND_A_TENDER",
                        "ocid": ocid or None,
                        "release_id": rid or None,
                        "notice_url": notice_url,
                        "supplier_resolution_status": "PENDING_RELEASE_DETAIL",
                    }

    raw = sorted(candidates.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in raw if x.get("current")]
    pre = sorted(pre_by_id.values(), key=lambda x: x.get("published") or "", reverse=True)
    awards = list(award_rows.values())
    write_jsonl(out / "raw.jsonl", raw)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "pre_tender.jsonl", pre)
    write_jsonl(out / "awards.jsonl", awards)

    truncated = any(e.get("error") == "TRUNCATED_BY_PAGE_CAP" for e in errors)
    stats = {
        "source": "UK_FTS_OCDS",
        "portal": "UK_FIND_A_TENDER",
        "grain": ["NOTICE_FIRST_TENDER", "PRE_TENDER_RADAR", "AWARD"],
        "updated_from": updated_from,
        "updated_to": updated_to,
        "lookback_days": args.lookback_days,
        "max_pages_per_stage": args.max_pages,
        "page_size": page_size,
        "releases_by_stage": releases_by_stage,
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "pre_tender_materialized": len(pre),
        "awards_materialized": len(awards),
        "document_routes": sum(bool((x.get("route") or {}).get("document_urls")) for x in raw),
        "competition_signal_rows": sum(x.get("tenderers_received_observed") is not None for x in raw)
        + sum(x.get("tenderers_received_observed") is not None for x in awards),
        "truncated_by_page_cap": truncated,
        "generated_at": now.isoformat(),
        "errors": errors,
        "telemetry": telemetry,
        "source_url": BASE,
        "semantics": "Planning, tender and award stages are paginated independently. Cursor URLs are opaque. Historical awards and pre-tender planning never count as live tender opportunities.",
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not (raw or pre or awards):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
