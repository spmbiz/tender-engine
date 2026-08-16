from __future__ import annotations

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

BASE = "https://ocds-api.etenders.gov.za/api/OCDSReleases"
UA = "Tender-Engine/5.5 (+public procurement research; South Africa National Treasury OCDS)"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_page(session: requests.Session, page: int, size: int, date_from: str, date_to: str) -> dict[str, Any]:
    params = {"PageNumber": page, "PageSize": size, "dateFrom": date_from, "dateTo": date_to}
    last = None
    for attempt in range(5):
        try:
            r = session.get(BASE, params=params, timeout=90)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("SA OCDS API returned non-object JSON")
        except Exception as exc:
            last = exc
            if attempt < 4:
                time.sleep(min(12, 2 ** attempt))
    raise RuntimeError(f"SA OCDS API failed: {last!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/ZA_ETENDERS_OCDS")))
    ap.add_argument("--lookback-days", type=int, default=int(os.getenv("ZA_LOOKBACK_DAYS", "90")))
    ap.add_argument("--page-size", type=int, default=int(os.getenv("ZA_PAGE_SIZE", "1000")))
    ap.add_argument("--max-pages", type=int, default=int(os.getenv("ZA_MAX_PAGES", "20")))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=max(1, args.lookback_days))).date().isoformat()
    date_to = now.date().isoformat()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    candidates: dict[str, dict[str, Any]] = {}
    awards: list[dict[str, Any]] = []
    telemetry = []
    errors = []
    for page in range(1, max(1, args.max_pages) + 1):
        try:
            pkg = fetch_page(session, page, args.page_size, date_from, date_to)
        except Exception as exc:
            errors.append({"page": page, "error": repr(exc)})
            break
        releases = pkg.get("releases") or []
        if not isinstance(releases, list):
            errors.append({"page": page, "error": "RELEASES_NOT_LIST"})
            break
        telemetry.append({
            "page": page,
            "releases": len(releases),
            "next": (pkg.get("links") or {}).get("next") if isinstance(pkg.get("links"), dict) else None,
        })
        if not releases:
            break
        for release in releases:
            if not isinstance(release, dict):
                continue
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
        links = pkg.get("links") or {}
        if len(releases) < args.page_size or (isinstance(links, dict) and not links.get("next")):
            break

    raw = sorted(candidates.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in raw if x.get("current")]
    write_jsonl(out / "raw.jsonl", raw)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "awards.jsonl", awards)
    stats = {
        "source": "ZA_ETENDERS_OCDS",
        "grain": ["NOTICE_FIRST_TENDER", "AWARD"],
        "date_from": date_from,
        "date_to": date_to,
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "awards_materialized": len(awards),
        "document_routes": sum(bool((x.get("route") or {}).get("document_urls")) for x in raw),
        "competition_signal_rows": sum(x.get("tenderers_received_observed") is not None for x in raw)
        + sum(x.get("tenderers_received_observed") is not None for x in awards),
        "generated_at": now.isoformat(),
        "errors": errors,
        "telemetry": telemetry,
        "source_url": BASE,
        "semantics": "OCDS tenderers list count is preserved as an observed competition signal when published; it is never invented when absent.",
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not raw and not awards:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
