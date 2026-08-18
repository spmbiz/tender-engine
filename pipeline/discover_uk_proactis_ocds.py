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
    from pipeline.ocds_release_normalizer import release_awards, release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_awards, release_to_candidate

SOURCES = {
    "UK_PCS_OCDS": {
        "portal": "PUBLIC_CONTRACTS_SCOTLAND",
        "base": "https://api.publiccontractsscotland.gov.uk/v1",
        "locale": None,
        "contract_types": [2, 5, 12, 21, 22, 23, 24, 102],
        "award_types": [3, 6, 13, 25, 103, 104],
        "pre_types": [1, 4, 101],
    },
    "UK_SELL2WALES_OCDS": {
        "portal": "SELL2WALES",
        "base": "https://api.sell2wales.gov.wales/v1",
        "locale": 2057,
        "contract_types": [2, 5, 12, 21, 22, 23, 24, 51],
        "award_types": [3, 6, 13, 25, 53, 55],
        "pre_types": [1, 4, 52, 54],
    },
}
UA = "Tender-Engine/5.6 (+public procurement research; official Proactis OCDS API)"


def month_pairs(count: int, now: datetime) -> list[tuple[int, int]]:
    y, m = now.year, now.month
    out = []
    for _ in range(max(1, count)):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_pkg(url: str, params: dict[str, Any], allow_incomplete_tls: bool) -> tuple[dict[str, Any], bool, float]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})
    last = None
    started = time.monotonic()
    for attempt in range(6):
        try:
            r = session.get(url, params=params, timeout=60, verify=True)
            r.raise_for_status()
            data = r.json()
            return (data if isinstance(data, dict) else {}), False, time.monotonic() - started
        except requests.exceptions.SSLError as exc:
            last = exc
            if allow_incomplete_tls:
                r = session.get(url, params=params, timeout=60, verify=False)
                r.raise_for_status()
                data = r.json()
                return (data if isinstance(data, dict) else {}), True, time.monotonic() - started
        except Exception as exc:
            last = exc
        if attempt < 5:
            time.sleep(min(20, 2 ** attempt))
    raise RuntimeError(f"Proactis API failed: {last!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES), default=os.getenv("PROACTIS_SOURCE", "UK_PCS_OCDS"))
    ap.add_argument("--output", type=Path)
    ap.add_argument("--months", type=int, default=int(os.getenv("PROACTIS_MONTHS", "2")))
    ap.add_argument("--workers", type=int, default=int(os.getenv("PROACTIS_WORKERS", "8")))
    args = ap.parse_args()
    cfg = SOURCES[args.source]
    out = args.output or Path(os.getenv("DISCOVERY_OUT", f"discovery/global/{args.source}"))
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    allow_incomplete_tls = os.getenv("PROACTIS_ALLOW_INCOMPLETE_TLS", "0") == "1"
    candidates: dict[str, dict[str, Any]] = {}
    awards: list[dict[str, Any]] = []
    pre: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    critical_errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    tls_fallbacks = 0

    notice_types = cfg["contract_types"] + cfg["award_types"] + cfg["pre_types"]
    tasks: list[tuple[str, int, dict[str, Any]]] = []
    for year, month in month_pairs(args.months, now):
        date_from = f"{month:02d}-{year}"
        for notice_type in notice_types:
            params: dict[str, Any] = {"dateFrom": date_from, "noticeType": notice_type, "outputType": 0}
            if cfg.get("locale"):
                params["locale"] = cfg["locale"]
            tasks.append((date_from, notice_type, params))

    fetched: list[tuple[str, int, dict[str, Any], bool, float]] = []
    workers = max(1, min(args.workers, len(tasks) or 1, 12))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_pkg, cfg["base"] + "/Notices", params, allow_incomplete_tls): (date_from, notice_type)
            for date_from, notice_type, params in tasks
        }
        for future in as_completed(futures):
            date_from, notice_type = futures[future]
            try:
                pkg, tls_fallback, elapsed = future.result()
                fetched.append((date_from, notice_type, pkg, tls_fallback, elapsed))
            except Exception as exc:
                problem = {"month": date_from, "notice_type": notice_type, "error": repr(exc)}
                if notice_type in cfg["contract_types"]:
                    problem["impact"] = "LIVE_CONTRACT_COVERAGE"
                    critical_errors.append(problem)
                else:
                    problem["impact"] = "AUXILIARY_PRE_OR_AWARD_ONLY"
                    warnings.append(problem)

    for date_from, notice_type, pkg, tls_fallback, elapsed in sorted(fetched, key=lambda x: (x[0], x[1])):
        tls_fallbacks += int(tls_fallback)
        releases = pkg.get("releases") or []
        if not isinstance(releases, list):
            releases = []
        telemetry.append({
            "month": date_from,
            "notice_type": notice_type,
            "releases": len(releases),
            "tls_fallback": tls_fallback,
            "elapsed_seconds": round(elapsed, 3),
        })
        for release in releases:
            if not isinstance(release, dict):
                continue
            ocid = str(release.get("ocid") or "").strip()
            public_url = f"{cfg['base']}/Notice?id={ocid}"
            if cfg.get("locale"):
                public_url += f"&locale={cfg['locale']}"
            if notice_type in cfg["contract_types"]:
                cand = release_to_candidate(release, source=args.source, portal=cfg["portal"], notice_url=public_url, now=now)
                if cand:
                    candidates[cand["candidate_id"]] = cand
            elif notice_type in cfg["award_types"]:
                found = release_awards(release, source=args.source, portal=cfg["portal"], notice_url=public_url)
                if found:
                    awards.extend(found)
                else:
                    awards.append({
                        "grain": "AWARD_NOTICE",
                        "source": args.source,
                        "portal": cfg["portal"],
                        "ocid": ocid or None,
                        "notice_url": public_url,
                        "supplier_resolution_status": "PENDING_RELEASE_DETAIL",
                    })
            else:
                cand = release_to_candidate(release, source=args.source, portal=cfg["portal"], notice_url=public_url, now=now)
                if cand:
                    cand["grain"] = "PRE_TENDER_RADAR"
                    cand["current"] = True
                    pre.append(cand)

    raw = sorted(candidates.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in raw if x.get("current")]
    write_jsonl(out / "raw.jsonl", raw)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "awards.jsonl", awards)
    write_jsonl(out / "pre_tender.jsonl", pre)

    contract_requests_planned = args.months * len(cfg["contract_types"])
    contract_requests_failed = len(critical_errors)
    contract_requests_succeeded = contract_requests_planned - contract_requests_failed
    # The API is queried by publication month, not by the portal's Current
    # Opportunities state. This is useful live discovery but not a mathematical
    # proof that every still-open older notice was traversed.
    bounded_publication_scope = True
    stats = {
        "source": args.source,
        "portal": cfg["portal"],
        "grain": ["NOTICE_FIRST_TENDER", "AWARD", "PRE_TENDER_RADAR"],
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "awards_materialized": len(awards),
        "pre_tender_materialized": len(pre),
        "document_routes": sum(bool((x.get("route") or {}).get("document_urls")) for x in raw),
        "months": args.months,
        "workers": workers,
        "requests_planned": len(tasks),
        "requests_succeeded": len(fetched),
        "contract_requests_planned": contract_requests_planned,
        "contract_requests_succeeded": contract_requests_succeeded,
        "contract_requests_failed": contract_requests_failed,
        "enumeration_mode": "BOUNDED_PUBLICATION_MONTHS",
        "enumeration_exhausted": False,
        "enumeration_complete": False,
        "live_coverage_credit_allowed": False if args.source == "UK_PCS_OCDS" else None,
        "coverage_semantics": "PCS API list queries are publication-month bounded; even zero critical API errors do not prove traversal of the portal's entire Current Opportunities universe.",
        "generated_at": now.isoformat(),
        "errors": sorted(critical_errors, key=lambda x: (x.get("month", ""), x.get("notice_type", 0))),
        "warnings": sorted(warnings, key=lambda x: (x.get("month", ""), x.get("notice_type", 0))),
        "telemetry": telemetry,
        "tls_fallbacks": tls_fallbacks,
        "incomplete_tls_fallback_allowed": allow_incomplete_tls,
        "source_url": cfg["base"],
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not raw and not awards and not pre:
        raise SystemExit(2)


if __name__ == "__main__":
    main()