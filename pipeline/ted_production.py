from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("discover_ted.py")
MERGER = Path(__file__).with_name("merge_ted_year_shards.py")
FIRST_ACTIVE_YEAR = int(os.getenv("TED_RECONCILE_FIRST_YEAR", "2016"))
RECONCILE_PARALLELISM = max(1, min(4, int(os.getenv("TED_RECONCILE_PARALLELISM", "2"))))
DELTA_RECENT_DAYS = max(1, int(os.getenv("TED_DELTA_RECENT_DAYS", "3")))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"INVALID_JSONL {path}:{line_no}: {exc!r}") from exc
            if isinstance(row, dict):
                yield row


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _candidate_key(row: dict[str, Any]) -> str | None:
    cid = str(row.get("candidate_id") or "").strip()
    if cid:
        return cid
    pub = str(row.get("publication_number") or "").strip()
    return f"TED:{pub}" if pub else None


def build_delta_queries(now: datetime, recent_days: int = DELTA_RECENT_DAYS) -> dict[str, str]:
    now = now.astimezone(timezone.utc)
    today = now.strftime("%Y%m%d")
    recent_start = (now - timedelta(days=max(1, recent_days))).strftime("%Y%m%d")
    return {
        "future-deadline": (
            "form-type = competition AND ("
            f"deadline >= {today} OR "
            f"deadline-receipt-request >= {today} OR "
            f"deadline-receipt-tender-date-lot >= {today})"
        ),
        "recent-publication": f"PD = ({recent_start} <> {today}) AND form-type = competition",
    }


def build_year_queries(first_year: int, current_year: int) -> dict[int, str]:
    if current_year < first_year:
        raise ValueError(f"current_year {current_year} < first_year {first_year}")
    return {
        year: f"PD = ({year}0101 <> {year}1231) AND form-type = competition"
        for year in range(first_year, current_year + 1)
    }


def _child_env(out: Path, query: str, *, hard_max_pages: int | None = None, reconcile: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["DISCOVERY_OUT"] = str(out)
    env["TED_QUERY"] = query
    env["TED_SCOPE"] = "ACTIVE"
    env["TED_DISABLE_PRODUCTION_ORCHESTRATOR"] = "1"
    if hard_max_pages is not None:
        env["TED_HARD_MAX_PAGES"] = str(hard_max_pages)
    else:
        env.pop("TED_HARD_MAX_PAGES", None)
    if reconcile:
        parent_delay = float(env.get("TED_PAGE_DELAY_SECONDS", "0.05") or 0.05)
        env["TED_PAGE_DELAY_SECONDS"] = str(max(parent_delay, float(os.getenv("TED_RECONCILE_PAGE_DELAY_SECONDS", "0.12"))))
        parent_retries = int(env.get("TED_REQUEST_RETRIES", "7") or 7)
        env["TED_REQUEST_RETRIES"] = str(max(parent_retries, 8))
    return env


def _run_child(label: str, query: str, out: Path, *, hard_max_pages: int | None = None, reconcile: bool = False) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "runner.log"
    env = _child_env(out, query, hard_max_pages=hard_max_pages, reconcile=reconcile)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(SCRIPT.parent.parent),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    stats = _read_json(out / "stats.json")
    complete = bool(
        proc.returncode == 0
        and stats.get("enumeration_complete") is True
        and not stats.get("errors")
        and not stats.get("truncated_by_page_cap")
    )
    total = stats.get("total_reported")
    if complete and total is not None:
        try:
            complete = int(stats.get("source_items_seen") or 0) >= int(total)
        except Exception:
            complete = False
    return {
        "label": label,
        "query": query,
        "out": str(out),
        "process_exit_code": proc.returncode,
        "complete": complete,
        "stats": stats,
    }


def _merge_delta_lanes(results: list[dict[str, Any]], output_dir: Path, now: datetime) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    lane_summaries = []
    source_items_seen = 0

    for result in results:
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        lane_summaries.append({
            "label": result.get("label"),
            "query": result.get("query"),
            "process_exit_code": result.get("process_exit_code"),
            "complete": result.get("complete"),
            "pages": stats.get("pages"),
            "total_reported": stats.get("total_reported"),
            "source_items_seen": stats.get("source_items_seen"),
            "materialized_unique": stats.get("materialized_unique"),
            "current_materialized": stats.get("current_materialized"),
            "rate_limit_events": stats.get("rate_limit_events"),
            "malformed_json_retry_events": stats.get("malformed_json_retry_events"),
            "errors": stats.get("errors") or [],
        })
        try:
            source_items_seen += int(stats.get("source_items_seen") or 0)
        except Exception:
            pass
        if result.get("complete") is not True:
            errors.append({
                "type": "TED_DELTA_LANE_INCOMPLETE",
                "lane": result.get("label"),
                "process_exit_code": result.get("process_exit_code"),
                "stats_errors": stats.get("errors") or [],
            })
        lane_dir = Path(str(result.get("out") or ""))
        for row in _iter_jsonl(lane_dir / "active.jsonl"):
            key = _candidate_key(row)
            if not key:
                errors.append({"type": "TED_DELTA_ROW_ID_MISSING", "lane": result.get("label")})
                continue
            previous = records.get(key)
            if previous is None:
                records[key] = row
            elif previous != row:
                # The two queries overlap heavily. Preserve one authoritative-ID row
                # but never hide a content disagreement between lanes.
                errors.append({"type": "TED_DELTA_EXACT_ID_CONTENT_COLLISION", "candidate_id": key})

    rows = sorted(records.values(), key=lambda r: (str(r.get("publication_date") or ""), str(r.get("candidate_id") or "")))
    current = [r for r in rows if r.get("current") is True]
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "active.jsonl", rows)
    _write_jsonl(output_dir / "current.jsonl", current)

    complete = all(r.get("complete") is True for r in results) and not errors
    stats = {
        "source": "TED",
        "scope": "ACTIVE",
        "enumeration_mode": "DELTA_FUTURE_DEADLINE_PLUS_RECENT_PUBLICATION",
        "listing_contract": "TED_DELTA_FUTURE_DEADLINE_PLUS_RECENT_PUBLICATION_V1",
        "query": "UNION(future-deadline, recent-publication)",
        "delta_recent_days": DELTA_RECENT_DAYS,
        "pages": sum(int((r.get("stats") or {}).get("pages") or 0) for r in results),
        # The lanes overlap, so summing totalNoticeCount would falsely imply a
        # disjoint universe. Keep per-lane totals below and leave the union total
        # unknown rather than inventing one.
        "total_reported": None,
        "source_items_seen": source_items_seen,
        "materialized_unique": len(rows),
        "current_materialized": len(current),
        "open_confirmed_by_future_deadline": sum(1 for r in current if r.get("currentness_evidence") == "PARSED_FUTURE_DEADLINE"),
        "open_unverified_no_parseable_deadline": sum(1 for r in current if r.get("currentness_evidence") == "NO_PARSEABLE_DEADLINE"),
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": bool(current),
        # DELTA is deliberately a fast actionable lane, not proof of the full TED
        # ACTIVE universe. Only the year-sharded reconcile may receive full-credit.
        "live_coverage_credit_allowed": False,
        "truncated_by_page_cap": False,
        "errors": errors,
        "lanes": lane_summaries,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "semantics": "Frequent TED delta lane. Exhaustively enumerates the union of all competition notices with at least one future deadline field plus a recent-publication recall window, without applying a publication lookback to the future-deadline lane. This is intentionally not full ACTIVE-universe coverage; no-deadline older notices remain the responsibility of the deep year-sharded reconcile. ACTIVE scope itself is never treated as open-deadline evidence.",
    }
    _write_json(output_dir / "stats.json", stats)
    return stats


def _copy_shard_proofs(year_root: Path, output_dir: Path, years: list[int]) -> None:
    proof_root = output_dir / "shard-proofs"
    proof_root.mkdir(parents=True, exist_ok=True)
    for year in years:
        src = year_root / f"year-{year}" / "stats.json"
        if src.exists():
            shutil.copy2(src, proof_root / f"year-{year}-stats.json")


def _run_delta(output_dir: Path, now: datetime) -> int:
    lane_root = output_dir.parent / f"{output_dir.name}-delta-lanes"
    queries = build_delta_queries(now)
    results = [
        _run_child(label, query, lane_root / label, reconcile=False)
        for label, query in queries.items()
    ]
    stats = _merge_delta_lanes(results, output_dir, now)
    rc = 0 if stats.get("enumeration_complete") is True and stats.get("current_materialized", 0) else 3
    (output_dir / "adapter_exit_code.txt").write_text(f"{rc}\n", encoding="utf-8")
    return rc


def _run_reconcile(output_dir: Path, now: datetime) -> int:
    queries = build_year_queries(FIRST_ACTIVE_YEAR, now.year)
    years = sorted(queries)
    shard_root = output_dir.parent / f"{output_dir.name}-year-shards"
    results: dict[int, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=RECONCILE_PARALLELISM) as pool:
        futures = {
            pool.submit(_run_child, f"year-{year}", query, shard_root / f"year-{year}", reconcile=True): year
            for year, query in queries.items()
        }
        for future in as_completed(futures):
            year = futures[future]
            try:
                results[year] = future.result()
            except Exception as exc:
                results[year] = {
                    "label": f"year-{year}",
                    "query": queries[year],
                    "out": str(shard_root / f"year-{year}"),
                    "process_exit_code": 99,
                    "complete": False,
                    "stats": {"errors": [{"type": "TED_YEAR_SHARD_ORCHESTRATOR_EXCEPTION", "error": repr(exc)}]},
                }

    expected_csv = ",".join(str(y) for y in years)
    output_dir.mkdir(parents=True, exist_ok=True)
    merge_log = output_dir / "merge.log"
    with merge_log.open("w", encoding="utf-8") as log:
        merge_proc = subprocess.run(
            [
                sys.executable,
                str(MERGER),
                "--root", str(shard_root),
                "--output", str(output_dir),
                "--expected-years", expected_csv,
            ],
            cwd=str(MERGER.parent.parent),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )

    _copy_shard_proofs(shard_root, output_dir, years)

    # Independent one-page count probe of the unpartitioned ACTIVE competition
    # query. This does not claim page exhaustion; it exists only to detect a year
    # outside our partition range or a shard-count gap. A mismatch keeps coverage
    # fail-closed even if every individual year exhausted cleanly.
    probe = _run_child(
        "unpartitioned-total-probe",
        "form-type = competition",
        shard_root / "unpartitioned-total-probe",
        hard_max_pages=1,
        reconcile=False,
    )
    probe_stats = probe.get("stats") if isinstance(probe.get("stats"), dict) else {}
    probe_total = probe_stats.get("total_reported")

    stats = _read_json(output_dir / "stats.json")
    errors = list(stats.get("errors") or []) if isinstance(stats, dict) else []
    shard_sum = stats.get("source_items_seen") if isinstance(stats, dict) else None
    count_match = False
    try:
        count_match = probe_total is not None and shard_sum is not None and int(probe_total) == int(shard_sum)
    except Exception:
        count_match = False
    if not count_match:
        errors.append({
            "type": "TED_YEAR_SHARD_TOTAL_MISMATCH",
            "unpartitioned_total_reported": probe_total,
            "year_shard_source_items_seen": shard_sum,
            "semantics": "Fail-closed boundary check; may also reveal live index drift during the multi-shard run.",
        })

    shard_failures = [
        {
            "year": year,
            "process_exit_code": result.get("process_exit_code"),
            "stats_errors": (result.get("stats") or {}).get("errors") or [],
        }
        for year, result in sorted(results.items())
        if result.get("complete") is not True
    ]
    if shard_failures:
        errors.append({"type": "TED_YEAR_SHARD_CHILD_FAILURES", "failures": shard_failures})

    if not isinstance(stats, dict):
        stats = {
            "source": "TED",
            "scope": "ACTIVE",
            "enumeration_mode": "YEAR_SHARDED_ACTIVE_COMPETITION",
            "listing_contract": "TED_ACTIVE_YEAR_SHARDS_V2_PRODUCTION",
            "expected_years": years,
            "complete_years": [],
            "source_items_seen": 0,
            "materialized_unique": 0,
            "current_materialized": 0,
        }
    stats["listing_contract"] = "TED_ACTIVE_YEAR_SHARDS_V2_PRODUCTION"
    stats["production_lane"] = "RECONCILE_YEAR_SHARDED_ACTIVE"
    stats["reconcile_parallelism"] = RECONCILE_PARALLELISM
    stats["first_active_year"] = FIRST_ACTIVE_YEAR
    stats["unpartitioned_active_total_reported"] = probe_total
    stats["year_shard_sum_matches_active_total"] = count_match
    stats["merge_exit_code"] = merge_proc.returncode
    stats["errors"] = errors
    complete = bool(
        merge_proc.returncode == 0
        and not shard_failures
        and count_match
        and stats.get("enumeration_complete") is True
        and not errors
    )
    stats["enumeration_exhausted"] = complete
    stats["enumeration_complete"] = complete
    stats["live_candidate_capable"] = bool(stats.get("current_materialized"))
    stats["live_coverage_credit_allowed"] = complete and bool(stats.get("current_materialized"))
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    stats["semantics"] = "Production TED reconcile. ACTIVE competition notices are independently enumerated in deterministic publication-year shards from 2016 through the current UTC year, with at most two shards in flight by default. Every shard must prove iteration-token exhaustion and reported-count coverage; the exact-ID merge must succeed; and the summed shard source count must equal an independent unpartitioned ACTIVE total probe before full coverage credit is allowed. ACTIVE scope remains separate from deadline evidence, so past-only deadlines are closed and missing deadlines remain open-unverified rather than assumed satisfied."
    _write_json(output_dir / "stats.json", stats)
    _write_json(output_dir / "orchestrator.json", {
        "schema": "TED_PRODUCTION_ORCHESTRATOR_V1",
        "mode": "reconcile",
        "expected_years": years,
        "parallelism": RECONCILE_PARALLELISM,
        "merge_exit_code": merge_proc.returncode,
        "unpartitioned_total_reported": probe_total,
        "year_shard_source_items_seen": shard_sum,
        "count_match": count_match,
        "children": {
            str(year): {
                "process_exit_code": result.get("process_exit_code"),
                "complete": result.get("complete"),
                "pages": (result.get("stats") or {}).get("pages"),
                "total_reported": (result.get("stats") or {}).get("total_reported"),
                "source_items_seen": (result.get("stats") or {}).get("source_items_seen"),
                "errors": (result.get("stats") or {}).get("errors") or [],
            }
            for year, result in sorted(results.items())
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    rc = 0 if complete else 3
    (output_dir / "adapter_exit_code.txt").write_text(f"{rc}\n", encoding="utf-8")
    return rc


def run_production(mode: str, output_dir: Path | str) -> int:
    mode = str(mode or "").strip().lower()
    if mode not in {"delta", "reconcile"}:
        raise ValueError(f"unsupported TED production mode: {mode!r}")
    out = Path(output_dir)
    now = datetime.now(timezone.utc)
    if mode == "delta":
        return _run_delta(out, now)
    return _run_reconcile(out, now)
