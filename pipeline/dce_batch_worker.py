from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def run_one(queue: str, line_no: int, out: str):
    cmd = [
        sys.executable,
        "pipeline/dce_worker_v2.py",
        "--queue",
        queue,
        "--line",
        str(line_no),
        "--out",
        out,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return {
        "line": line_no,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--lines", required=True, help="comma-separated 1-based queue lines")
    ap.add_argument("--out", default="out")
    ap.add_argument("--concurrency", type=int, default=int(os.getenv("DCE_LOCAL_CONCURRENCY", "2")))
    args = ap.parse_args()

    lines = [int(x.strip()) for x in args.lines.split(",") if x.strip()]
    Path(args.out).mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futs = {pool.submit(run_one, args.queue, line, args.out): line for line in lines}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"line": futs[fut], "returncode": 99, "stdout": "", "stderr": repr(exc)}
            results.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)

    results.sort(key=lambda r: r["line"])
    Path(args.out, "batch_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    # Individual worker failures must not suppress successful candidates. CI stays green if material manifests exist;
    # batch_results.json carries retryable failures to the aggregator/agent.
    print(json.dumps({"lines": lines, "results": len(results), "failures": sum(1 for r in results if r["returncode"] != 0)}, indent=2))


if __name__ == "__main__":
    main()
