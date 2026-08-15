from __future__ import annotations

import argparse
import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

from build_matrix import BROWSER_PORTALS, SUPPORTED, load_lines
from global_admission import dynamic_tender_parallel

MATRIX_JOB_LIMIT = 256
RUNNER_PARALLEL_LIMIT = 20
DEFAULT_BROWSER_MAX_JOBS_PER_SHARD = 12
DEFAULT_HTTP_MAX_JOBS_PER_SHARD = 32


def _norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _requested_parallel_default() -> int:
    # The autonomous controller computes the actually available global runner
    # capacity and exports it as DCE_REQUESTED_MAX_PARALLEL. Prefer that live
    # budget over the workflow's legacy DCE_MAX_PARALLEL fallback. A hard cap of
    # RUNNER_PARALLEL_LIMIT is still enforced below.
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
    ordered = sorted(jobs, key=lambda j: (j["portal"], j["line"]))
    for i, job in enumerate(ordered):
        buckets[i % count].append(job)
    return [b for b in buckets if b]


def _allocate_shards(browser_n: int, http_n: int, desired: int) -> tuple[int, int]:
    total = browser_n + http_n
    if total == 0:
        return 0, 0
    if browser_n == 0:
        return 0, min(desired, http_n)
    if http_n == 0:
        return min(desired, browser_n), 0
    browser_share = max(1, round(desired * browser_n / total))
    http_share = max(1, desired - browser_share)
    browser_share = min(browser_share, browser_n)
    http_share = min(http_share, http_n)
    while browser_share + http_share < desired:
        if browser_share < browser_n:
            browser_share += 1
        elif http_share < http_n:
            http_share += 1
        else:
            break
    return browser_share, http_share


def _adaptive_count(n: int, active_slots: int, target_waves: int, max_jobs_per_shard: int) -> tuple[int, int]:
    if n <= 0:
        return 0, 0
    active_slots = max(1, min(active_slots, n))
    target_waves = max(1, target_waves)
    natural = math.ceil(n / (active_slots * target_waves))
    jobs_per_shard = max(1, min(max_jobs_per_shard, natural))
    shard_count = math.ceil(n / jobs_per_shard)
    return shard_count, jobs_per_shard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--exclude-queue", default=os.getenv("DCE_EXCLUDE_QUEUE", ""))
    ap.add_argument("--max-shards", type=int, default=int(os.getenv("DCE_MAX_SHARDS", str(MATRIX_JOB_LIMIT))))
    ap.add_argument("--jobs-per-shard", type=int, default=int(os.getenv("DCE_TARGET_JOBS_PER_SHARD", "0")), help="0/1/2 = adaptive legacy-compatible; >2 = manual")
    ap.add_argument("--target-waves", type=int, default=int(os.getenv("DCE_TARGET_WAVES", "1")))
    ap.add_argument("--browser-max-jobs-per-shard", type=int, default=int(os.getenv("DCE_BROWSER_MAX_JOBS_PER_SHARD", str(DEFAULT_BROWSER_MAX_JOBS_PER_SHARD))))
    ap.add_argument("--http-max-jobs-per-shard", type=int, default=int(os.getenv("DCE_HTTP_MAX_JOBS_PER_SHARD", str(DEFAULT_HTTP_MAX_JOBS_PER_SHARD))))
    ap.add_argument("--max-jobs", type=int, default=int(os.getenv("MAX_DCE_JOBS", "320")))
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
    target_waves = max(1, args.target_waves)
    browser_cap = max(1, args.browser_max_jobs_per_shard)
    http_cap = max(1, args.http_max_jobs_per_shard)
    exclude_path = Path(args.exclude_queue) if args.exclude_queue else None
    excluded_ids, excluded_title_buyers = _load_exclusions(exclude_path)

    jobs: list[dict] = []
    skipped: list[dict] = []
    seen_candidates: set[str] = set()
    seen_title_buyers: set[tuple[str, str]] = set()
    portal_counts: Counter[str] = Counter()

    for line_no, rec in load_lines(Path(args.queue)):
        status = str(rec.get("status") or "QUEUED").upper()
        if status not in {"QUEUED", "READY", "DCE_PENDING", "AUTO_DCE_PREFETCH"}:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"status:{status}"})
            continue
        portal = str(rec.get("portal") or rec.get("portal_key") or rec.get("source") or "").upper()
        if portal not in SUPPORTED:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"unsupported:{portal}"})
            continue
        candidate_id = str(rec.get("candidate_id") or f"line-{line_no}").strip()
        cid_key, tb_key = _identity_keys(rec)
        if cid_key in excluded_ids or (tb_key and tb_key in excluded_title_buyers):
            skipped.append({"line": line_no, "candidate_id": candidate_id, "reason": "already_in_exclude_queue_exact_identity"})
            continue
        if cid_key in seen_candidates or (tb_key and tb_key in seen_title_buyers):
            skipped.append({"line": line_no, "candidate_id": candidate_id, "reason": "duplicate_exact_identity_in_queue"})
            continue
        seen_candidates.add(cid_key)
        if tb_key:
            seen_title_buyers.add(tb_key)
        jobs.append({"line": line_no, "candidate_id": candidate_id, "portal": portal, "needs_browser": portal in BROWSER_PORTALS})
        portal_counts[portal] += 1
        if len(jobs) >= max_jobs:
            break

    # Zero admission is a deliberate defer, not a failure: preserve the durable
    # source selection and let the next controller cycle retry after capacity frees.
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

    sizing_mode = "adaptive"
    browser_target = 0
    http_target = 0
    if jobs and args.jobs_per_shard > 2:
        sizing_mode = "manual"
        fixed = max(3, args.jobs_per_shard)
        desired = min(max_shards, len(jobs), math.ceil(len(jobs) / fixed))
        browser_shards, http_shards = _allocate_shards(len(browser_jobs), len(http_jobs), desired)
        browser_target = fixed
        http_target = fixed
    elif jobs:
        active_target = min(max_parallel, len(jobs))
        browser_slots, http_slots = _allocate_shards(len(browser_jobs), len(http_jobs), active_target)
        browser_shards, browser_target = _adaptive_count(len(browser_jobs), browser_slots, target_waves, browser_cap)
        http_shards, http_target = _adaptive_count(len(http_jobs), http_slots, target_waves, http_cap)
        total_shards = browser_shards + http_shards
        if total_shards > max_shards:
            scale = total_shards / max_shards
            browser_target = max(browser_target, math.ceil(browser_target * scale)) if browser_jobs else 0
            http_target = max(http_target, math.ceil(http_target * scale)) if http_jobs else 0
            browser_shards = math.ceil(len(browser_jobs) / browser_target) if browser_jobs else 0
            http_shards = math.ceil(len(http_jobs) / http_target) if http_jobs else 0
    else:
        browser_shards = 0
        http_shards = 0

    include: list[dict] = []
    shard_idx = 0
    for kind, buckets, local_concurrency in (
        ("browser", _split_buckets(browser_jobs, browser_shards), max(1, args.browser_local_concurrency)),
        ("http", _split_buckets(http_jobs, http_shards), max(1, args.http_local_concurrency)),
    ):
        for bucket in buckets:
            include.append({
                "shard": shard_idx,
                "kind": kind,
                "lines": ",".join(str(x["line"]) for x in bucket),
                "count": len(bucket),
                "needs_browser": kind == "browser",
                "local_concurrency": min(local_concurrency, len(bucket)),
                "portals": ",".join(sorted({x["portal"] for x in bucket})),
            })
            shard_idx += 1

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
        "target_waves": target_waves,
        "browser_jobs_per_shard_target": browser_target,
        "http_jobs_per_shard_target": http_target,
        "browser_max_jobs_per_shard": browser_cap,
        "http_max_jobs_per_shard": http_cap,
        "browser_local_concurrency": max(1, args.browser_local_concurrency),
        "http_local_concurrency": max(1, args.http_local_concurrency),
        "browser_candidates": len(browser_jobs),
        "http_candidates": len(http_jobs),
        "portal_counts": dict(sorted(portal_counts.items())),
        "skipped_count": len(skipped),
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
