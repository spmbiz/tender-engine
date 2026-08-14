from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path

from build_matrix import BROWSER_PORTALS, SUPPORTED, load_lines

MATRIX_JOB_LIMIT = 256
RUNNER_PARALLEL_LIMIT = 20


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--max-shards", type=int, default=int(os.getenv("DCE_MAX_SHARDS", str(MATRIX_JOB_LIMIT))))
    ap.add_argument("--jobs-per-shard", type=int, default=int(os.getenv("DCE_TARGET_JOBS_PER_SHARD", "1")))
    ap.add_argument("--max-jobs", type=int, default=int(os.getenv("MAX_DCE_JOBS", "320")))
    ap.add_argument("--max-parallel", type=int, default=int(os.getenv("DCE_MAX_PARALLEL", str(RUNNER_PARALLEL_LIMIT))))
    ap.add_argument("--browser-local-concurrency", type=int, default=int(os.getenv("DCE_BROWSER_LOCAL_CONCURRENCY", "1")))
    ap.add_argument("--http-local-concurrency", type=int, default=int(os.getenv("DCE_HTTP_LOCAL_CONCURRENCY", "4")))
    ap.add_argument("--out", default="dce_shards.json")
    args = ap.parse_args()

    # Matrix depth and simultaneous runner count are deliberately separate.
    # A deep queued matrix keeps the runner pool full as short shards finish.
    max_shards = max(1, min(MATRIX_JOB_LIMIT, args.max_shards))
    max_parallel = max(1, min(RUNNER_PARALLEL_LIMIT, args.max_parallel))
    jobs_per_shard = max(1, args.jobs_per_shard)
    max_jobs = max(1, args.max_jobs)

    jobs: list[dict] = []
    skipped: list[dict] = []
    seen_candidates: set[str] = set()
    portal_counts: Counter[str] = Counter()

    for line_no, rec in load_lines(Path(args.queue)):
        status = str(rec.get("status") or "QUEUED").upper()
        if status not in {"QUEUED", "READY", "DCE_PENDING"}:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"status:{status}"})
            continue
        portal = str(rec.get("portal") or rec.get("portal_key") or rec.get("source") or "").upper()
        if portal not in SUPPORTED:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"unsupported:{portal}"})
            continue
        candidate_id = str(rec.get("candidate_id") or f"line-{line_no}").strip()
        dedupe_key = candidate_id.casefold()
        if dedupe_key in seen_candidates:
            skipped.append({"line": line_no, "candidate_id": candidate_id, "reason": "duplicate_candidate_id"})
            continue
        seen_candidates.add(dedupe_key)
        jobs.append(
            {
                "line": line_no,
                "candidate_id": candidate_id,
                "portal": portal,
                "needs_browser": portal in BROWSER_PORTALS,
            }
        )
        portal_counts[portal] += 1
        if len(jobs) >= max_jobs:
            break

    browser_jobs = [j for j in jobs if j["needs_browser"]]
    http_jobs = [j for j in jobs if not j["needs_browser"]]
    desired = min(max_shards, max(1, math.ceil(len(jobs) / jobs_per_shard))) if jobs else 0
    browser_shards, http_shards = _allocate_shards(len(browser_jobs), len(http_jobs), desired)

    include: list[dict] = []
    shard_idx = 0
    for kind, buckets, local_concurrency in (
        ("browser", _split_buckets(browser_jobs, browser_shards), max(1, args.browser_local_concurrency)),
        ("http", _split_buckets(http_jobs, http_shards), max(1, args.http_local_concurrency)),
    ):
        for bucket in buckets:
            include.append(
                {
                    "shard": shard_idx,
                    "kind": kind,
                    "lines": ",".join(str(x["line"]) for x in bucket),
                    "count": len(bucket),
                    "needs_browser": kind == "browser",
                    "local_concurrency": min(local_concurrency, len(bucket)),
                    "portals": ",".join(sorted({x["portal"] for x in bucket})),
                }
            )
            shard_idx += 1

    payload = {"include": include}
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path("dce_shards_skipped.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    plan = {
        "candidate_count": len(jobs),
        "shard_count": len(include),
        "max_parallel": min(max_parallel, max(1, len(include))) if include else 0,
        "max_shards": max_shards,
        "matrix_job_limit": MATRIX_JOB_LIMIT,
        "jobs_per_shard_target": jobs_per_shard,
        "browser_candidates": len(browser_jobs),
        "http_candidates": len(http_jobs),
        "portal_counts": dict(sorted(portal_counts.items())),
        "skipped_count": len(skipped),
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
