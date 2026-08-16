from __future__ import annotations

import argparse
import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

from build_matrix import BROWSER_PORTALS, SUPPORTED, load_lines, resolve_dce_portal
from global_admission import dynamic_tender_parallel

MATRIX_JOB_LIMIT = 256
RUNNER_PARALLEL_LIMIT = 20
DEFAULT_BROWSER_MAX_JOBS_PER_SHARD = 12
DEFAULT_HTTP_MAX_JOBS_PER_SHARD = 32
DEFAULT_BROWSER_TARGET_JOBS_PER_SHARD = 2
DEFAULT_HTTP_TARGET_JOBS_PER_SHARD = 8


def _norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _requested_parallel_default() -> int:
    for key in ("DCE_REQUESTED_MAX_PARALLEL", "DCE_MAX_PARALLEL"):
        raw = os.getenv(key)
        if not raw:
            continue
        try:
            return int(raw)
        except Exception:
            continue
    return RUNNER_PARALLEL_LIMIT


def _identity_keys(rec: dict) -> tuple[str, tuple[str, str] | None]:
    cid = str(rec.get("candidate_id") or "").strip().casefold()
    title = _norm(rec.get("title"))
    buyer = _norm(rec.get("buyer"))
    title_buyer = (title, buyer) if title and buyer else None
    return cid, title_buyer


def _load_exclusions(path: Path | None) -> tuple[set[str], set[tuple[str, str]]]:
    ids: set[str] = set()
    title_buyers: set[tuple[str, str]] = set()
    if not path or not path.exists():
        return ids, title_buyers
    for _, rec in load_lines(path):
        cid, tb = _identity_keys(rec)
        if cid:
            ids.add(cid)
        if tb:
            title_buyers.add(tb)
    return ids, title_buyers


def _split_buckets(jobs: list[dict], count: int) -> list[list[dict]]:
    if not jobs or count <= 0:
        return []
    count = min(count, len(jobs))
    buckets = [[] for _ in range(count)]
    # Selection input is already ranked. Preserve that ordering so the first
    # active shards receive the highest-value candidates rather than letting
    # portal-name sorting delay a top-ranked opportunity behind lower ranks.
    ordered = sorted(jobs, key=lambda j: j["line"])
    for i, job in enumerate(ordered):
        buckets[i % count].append(job)
    return [b for b in buckets if b]


def _fit_matrix_limit(
    browser_n: int,
    http_n: int,
    browser_target: int,
    http_target: int,
    browser_cap: int,
    http_cap: int,
    max_shards: int,
) -> tuple[int, int, int, int]:
    browser_target = max(1, min(browser_cap, browser_target)) if browser_n else 0
    http_target = max(1, min(http_cap, http_target)) if http_n else 0
    while True:
        browser_shards = math.ceil(browser_n / browser_target) if browser_n else 0
        http_shards = math.ceil(http_n / http_target) if http_n else 0
        if browser_shards + http_shards <= max_shards:
            return browser_shards, http_shards, browser_target, http_target
        browser_pressure = (browser_shards / max(1, browser_target)) if browser_n and browser_target < browser_cap else -1
        http_pressure = (http_shards / max(1, http_target)) if http_n and http_target < http_cap else -1
        if browser_pressure < 0 and http_pressure < 0:
            return browser_shards, http_shards, browser_target, http_target
        if browser_pressure >= http_pressure and browser_target < browser_cap:
            browser_target += 1
        elif http_target < http_cap:
            http_target += 1
        elif browser_target < browser_cap:
            browser_target += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--exclude-queue", default=os.getenv("DCE_EXCLUDE_QUEUE", ""))
    ap.add_argument("--max-shards", type=int, default=int(os.getenv("DCE_MAX_SHARDS", str(MATRIX_JOB_LIMIT))))
    ap.add_argument(
        "--jobs-per-shard",
        type=int,
        default=int(os.getenv("DCE_TARGET_JOBS_PER_SHARD", "0")),
        help="0/1/2 = streaming kind-aware defaults; >2 = manual fixed target for both kinds",
    )
    ap.add_argument("--browser-max-jobs-per-shard", type=int, default=int(os.getenv("DCE_BROWSER_MAX_JOBS_PER_SHARD", str(DEFAULT_BROWSER_MAX_JOBS_PER_SHARD))))
    ap.add_argument("--http-max-jobs-per-shard", type=int, default=int(os.getenv("DCE_HTTP_MAX_JOBS_PER_SHARD", str(DEFAULT_HTTP_MAX_JOBS_PER_SHARD))))
    ap.add_argument("--browser-target-jobs-per-shard", type=int, default=int(os.getenv("DCE_BROWSER_TARGET_JOBS_PER_SHARD", str(DEFAULT_BROWSER_TARGET_JOBS_PER_SHARD))))
    ap.add_argument("--http-target-jobs-per-shard", type=int, default=int(os.getenv("DCE_HTTP_TARGET_JOBS_PER_SHARD", str(DEFAULT_HTTP_TARGET_JOBS_PER_SHARD))))
    ap.add_argument("--max-jobs", type=int, default=int(os.getenv("MAX_DCE_JOBS", "500")))
    ap.add_argument("--max-parallel", type=int, default=_requested_parallel_default())
    ap.add_argument("--browser-local-concurrency", type=int, default=int(os.getenv("DCE_BROWSER_LOCAL_CONCURRENCY", "2")))
    ap.add_argument("--http-local-concurrency", type=int, default=int(os.getenv("DCE_HTTP_LOCAL_CONCURRENCY", "8")))
    ap.add_argument("--out", default="dce_shards.json")
    args = ap.parse_args()

    max_shards = max(1, min(MATRIX_JOB_LIMIT, args.max_shards))
    requested_parallel = max(0, min(RUNNER_PARALLEL_LIMIT, args.max_parallel))
    admitted_parallel, admission = dynamic_tender_parallel(requested_parallel)
    max_parallel = max(0, min(RUNNER_PARALLEL_LIMIT, admitted_parallel))
    max_jobs = max(1, args.max_jobs)
    browser_cap = max(1, args.browser_max_jobs_per_shard)
    http_cap = max(1, args.http_max_jobs_per_shard)
    exclude_path = Path(args.exclude_queue) if args.exclude_queue else None
    excluded_ids, excluded_title_buyers = _load_exclusions(exclude_path)

    jobs: list[dict] = []
    skipped: list[dict] = []
    seen_candidates: set[str] = set()
    seen_title_buyers: set[tuple[str, str]] = set()
    portal_counts: Counter[str] = Counter()
    raw_portal_counts: Counter[str] = Counter()
    skip_reason_counts: Counter[str] = Counter()

    def skip(line_no: int, rec: dict, reason: str) -> None:
        skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": reason})
        category = reason.split(":", 1)[0]
        skip_reason_counts[category] += 1

    for line_no, rec in load_lines(Path(args.queue)):
        status = str(rec.get("status") or "QUEUED").upper()
        if status not in {"QUEUED", "READY", "DCE_PENDING", "AUTO_DCE_PREFETCH", "AUTO_DCE_PREFETCH_QWEN"}:
            skip(line_no, rec, f"status:{status}")
            continue
        portal, raw_portal = resolve_dce_portal(rec)
        raw_portal_counts[raw_portal or "UNKNOWN"] += 1
        if portal not in SUPPORTED:
            skip(line_no, rec, f"unsupported:{raw_portal}")
            continue
        candidate_id = str(rec.get("candidate_id") or f"line-{line_no}").strip()
        cid_key, tb_key = _identity_keys(rec)
        if cid_key in excluded_ids or (tb_key and tb_key in excluded_title_buyers):
            skip(line_no, rec, "already_in_exclude_queue_exact_identity")
            continue
        if cid_key in seen_candidates or (tb_key and tb_key in seen_title_buyers):
            skip(line_no, rec, "duplicate_exact_identity_in_queue")
            continue
        seen_candidates.add(cid_key)
        if tb_key:
            seen_title_buyers.add(tb_key)
        jobs.append({
            "line": line_no,
            "candidate_id": candidate_id,
            "portal": portal,
            "raw_portal": raw_portal,
            "needs_browser": portal in BROWSER_PORTALS,
        })
        portal_counts[portal] += 1
        if len(jobs) >= max_jobs:
            break

    if jobs and max_parallel <= 0:
        payload = {"include": []}
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        Path("dce_shards_skipped.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
        plan = {
            "candidate_count": 0,
            "deferred_candidate_count": len(jobs),
            "shard_count": 0,
            "max_parallel": 0,
            "requested_parallel": requested_parallel,
            "admission": admission,
            "sizing_mode": "deferred_global_admission",
            "portal_counts": dict(sorted(portal_counts.items())),
            "raw_portal_counts": dict(sorted(raw_portal_counts.items())),
            "skipped_count": len(skipped),
            "skip_reason_counts": dict(sorted(skip_reason_counts.items())),
            "matrix": payload,
        }
        Path("dce_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        gh = os.getenv("GITHUB_OUTPUT")
        if gh:
            with open(gh, "a", encoding="utf-8") as f:
                f.write("matrix=" + json.dumps(payload, separators=(",", ":")) + "\n")
                f.write("count=0\n")
                f.write("shard_count=0\n")
                f.write("max_parallel=0\n")
        print(json.dumps(plan, indent=2))
        return

    browser_jobs = [j for j in jobs if j["needs_browser"]]
    http_jobs = [j for j in jobs if not j["needs_browser"]]

    if jobs and args.jobs_per_shard > 2:
        sizing_mode = "manual_fixed"
        fixed = max(3, args.jobs_per_shard)
        browser_target = min(browser_cap, fixed) if browser_jobs else 0
        http_target = min(http_cap, fixed) if http_jobs else 0
    else:
        sizing_mode = "streaming_kind_fixed"
        browser_target = max(1, min(browser_cap, args.browser_target_jobs_per_shard)) if browser_jobs else 0
        http_target = max(1, min(http_cap, args.http_target_jobs_per_shard)) if http_jobs else 0

    if jobs:
        browser_shards, http_shards, browser_target, http_target = _fit_matrix_limit(
            len(browser_jobs),
            len(http_jobs),
            browser_target or DEFAULT_BROWSER_TARGET_JOBS_PER_SHARD,
            http_target or DEFAULT_HTTP_TARGET_JOBS_PER_SHARD,
            browser_cap,
            http_cap,
            max_shards,
        )
    else:
        browser_shards = 0
        http_shards = 0

    include: list[dict] = []
    browser_buckets = _split_buckets(browser_jobs, browser_shards)
    http_buckets = _split_buckets(http_jobs, http_shards)
    # Interleave route kinds so fast HTTP work is not stuck behind a long browser
    # prefix in the matrix. GitHub can continuously recycle finished runners.
    while browser_buckets or http_buckets:
        if browser_buckets:
            bucket = browser_buckets.pop(0)
            include.append({
                "kind": "browser",
                "lines": ",".join(str(x["line"]) for x in bucket),
                "count": len(bucket),
                "needs_browser": True,
                "local_concurrency": min(max(1, args.browser_local_concurrency), len(bucket)),
                "portals": ",".join(sorted({x["portal"] for x in bucket})),
            })
        if http_buckets:
            bucket = http_buckets.pop(0)
            include.append({
                "kind": "http",
                "lines": ",".join(str(x["line"]) for x in bucket),
                "count": len(bucket),
                "needs_browser": False,
                "local_concurrency": min(max(1, args.http_local_concurrency), len(bucket)),
                "portals": ",".join(sorted({x["portal"] for x in bucket})),
            })
    for shard_idx, item in enumerate(include):
        item["shard"] = shard_idx

    payload = {"include": include}
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path("dce_shards_skipped.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    plan = {
        "candidate_count": len(jobs),
        "shard_count": len(include),
        "max_parallel": min(max_parallel, max(1, len(include))) if include else 0,
        "requested_parallel": requested_parallel,
        "admission": admission,
        "max_shards": max_shards,
        "matrix_job_limit": MATRIX_JOB_LIMIT,
        "sizing_mode": sizing_mode,
        "manual_jobs_per_shard": args.jobs_per_shard if args.jobs_per_shard > 2 else None,
        "browser_jobs_per_shard_target": browser_target,
        "http_jobs_per_shard_target": http_target,
        "browser_max_jobs_per_shard": browser_cap,
        "http_max_jobs_per_shard": http_cap,
        "browser_local_concurrency": max(1, args.browser_local_concurrency),
        "http_local_concurrency": max(1, args.http_local_concurrency),
        "browser_candidates": len(browser_jobs),
        "http_candidates": len(http_jobs),
        "portal_counts": dict(sorted(portal_counts.items())),
        "raw_portal_counts": dict(sorted(raw_portal_counts.items())),
        "skipped_count": len(skipped),
        "skip_reason_counts": dict(sorted(skip_reason_counts.items())),
        "exclude_queue": str(exclude_path) if exclude_path else None,
        "matrix": payload,
    }
    Path("dce_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    gh = os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write("matrix=" + json.dumps(payload, separators=(",", ":")) + "\n")
            f.write(f"count={len(jobs)}\n")
            f.write(f"shard_count={len(include)}\n")
            f.write(f"max_parallel={plan['max_parallel']}\n")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
