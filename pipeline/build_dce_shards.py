from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from build_matrix import BROWSER_PORTALS, SUPPORTED, load_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--shards", type=int, default=int(os.getenv("DCE_SHARDS", "2")))
    ap.add_argument("--max-jobs", type=int, default=int(os.getenv("MAX_DCE_JOBS", "80")))
    ap.add_argument("--out", default="dce_shards.json")
    args = ap.parse_args()

    jobs = []
    skipped = []
    for line_no, rec in load_lines(Path(args.queue)):
        status = str(rec.get("status") or "QUEUED").upper()
        if status not in {"QUEUED", "READY", "DCE_PENDING"}:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"status:{status}"})
            continue
        portal = str(rec.get("portal") or rec.get("portal_key") or rec.get("source") or "").upper()
        if portal not in SUPPORTED:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"unsupported:{portal}"})
            continue
        jobs.append({"line": line_no, "portal": portal, "needs_browser": portal in BROWSER_PORTALS})
        if len(jobs) >= args.max_jobs:
            break

    shard_count = max(1, min(args.shards, len(jobs) or 1))
    buckets = [[] for _ in range(shard_count)]
    # Put browser-heavy candidates first, then round-robin for balance.
    ordered = sorted(jobs, key=lambda j: (not j["needs_browser"], j["line"]))
    for i, job in enumerate(ordered):
        buckets[i % shard_count].append(job)

    include = []
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        include.append(
            {
                "shard": idx,
                "lines": ",".join(str(x["line"]) for x in bucket),
                "count": len(bucket),
                "needs_browser": any(x["needs_browser"] for x in bucket),
            }
        )

    payload = {"include": include}
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path("dce_shards_skipped.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    gh = os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write("matrix=" + json.dumps(payload, separators=(",", ":")) + "\n")
            f.write(f"count={len(jobs)}\n")
            f.write(f"shard_count={len(include)}\n")
    print(json.dumps({"candidate_count": len(jobs), "shards": payload, "skipped": skipped}, indent=2))


if __name__ == "__main__":
    main()
