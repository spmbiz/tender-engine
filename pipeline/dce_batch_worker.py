from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RETRYABLE_STATUSES = {"ERROR_RETRYABLE"}
RATE_LIMIT_RE = re.compile(r"(?:\b429\b|too many requests|rate.?limit|retry-after)", re.I)


def slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:100]


def load_candidate(queue: str, line_no: int) -> dict:
    with Path(queue).open("r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, start=1):
            if n == line_no:
                obj = json.loads(line)
                return obj if isinstance(obj, dict) else {}
    return {}


def load_manifest(out: str, candidate_id: str) -> dict:
    path = Path(out) / slugify(candidate_id) / "manifest.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def run_one(queue: str, line_no: int, out: str, retries: int, timeout_seconds: int):
    candidate = load_candidate(queue, line_no)
    candidate_id = str(candidate.get("candidate_id") or f"line-{line_no}")
    attempts = []
    started = time.monotonic()

    for attempt in range(1, retries + 2):
        cmd = [
            sys.executable,
            "pipeline/dce_worker_v6.py",
            "--queue",
            queue,
            "--line",
            str(line_no),
            "--out",
            out,
        ]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_seconds)
            returncode = proc.returncode
            stdout = proc.stdout[-12000:]
            stderr = proc.stderr[-12000:]
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else ""
            stderr = ((exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else "") + f"\nWORKER_TIMEOUT_{timeout_seconds}s"

        manifest = load_manifest(out, candidate_id)
        status = str(manifest.get("status") or ("WORKER_ERROR" if returncode else "UNKNOWN"))
        error_text = "\n".join([stderr, str(manifest.get("error") or "")])
        rate_limited = bool(RATE_LIMIT_RE.search(error_text))
        attempts.append(
            {
                "attempt": attempt,
                "returncode": returncode,
                "status": status,
                "elapsed_seconds": round(time.monotonic() - t0, 3),
                "rate_limited": rate_limited,
                "stdout": stdout,
                "stderr": stderr,
            }
        )

        retryable = returncode != 0 or status in RETRYABLE_STATUSES or rate_limited
        if not retryable or attempt > retries:
            break
        time.sleep(min(4.0, 0.75 * attempt + random.random()))

    final = attempts[-1]
    return {
        "line": line_no,
        "candidate_id": candidate_id,
        "portal": str(candidate.get("portal") or candidate.get("source") or "").upper(),
        "returncode": final["returncode"],
        "status": final["status"],
        "attempt_count": len(attempts),
        "retries": max(0, len(attempts) - 1),
        "rate_limited": any(a["rate_limited"] for a in attempts),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "attempts": attempts,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--lines", required=True, help="comma-separated 1-based queue lines")
    ap.add_argument("--out", default="out")
    ap.add_argument("--concurrency", type=int, default=int(os.getenv("DCE_LOCAL_CONCURRENCY", "2")))
    ap.add_argument("--retries", type=int, default=int(os.getenv("DCE_ITEM_RETRIES", "1")))
    ap.add_argument("--timeout-seconds", type=int, default=int(os.getenv("DCE_ITEM_TIMEOUT_SECONDS", "150")))
    args = ap.parse_args()

    lines = [int(x.strip()) for x in args.lines.split(",") if x.strip()]
    Path(args.out).mkdir(parents=True, exist_ok=True)
    results = []
    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, min(args.concurrency, len(lines) or 1))) as pool:
        futs = {
            pool.submit(run_one, args.queue, line, args.out, max(0, args.retries), max(30, args.timeout_seconds)): line
            for line in lines
        }
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {
                    "line": futs[fut],
                    "candidate_id": None,
                    "portal": None,
                    "returncode": 99,
                    "status": "BATCH_EXCEPTION",
                    "attempt_count": 1,
                    "retries": 0,
                    "rate_limited": False,
                    "elapsed_seconds": 0,
                    "attempts": [{"attempt": 1, "error": repr(exc)}],
                }
            results.append(rec)
            print(json.dumps({k: rec[k] for k in rec if k != "attempts"}, ensure_ascii=False), flush=True)

    results.sort(key=lambda r: r["line"])
    Path(args.out, "batch_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "lines": lines,
        "results": len(results),
        "failures": sum(1 for r in results if r["returncode"] != 0),
        "retryable_final": sum(1 for r in results if r.get("status") in RETRYABLE_STATUSES),
        "retries": sum(int(r.get("retries") or 0) for r in results),
        "rate_limited": sum(1 for r in results if r.get("rate_limited")),
        "wall_seconds": round(time.monotonic() - wall_start, 3),
        "local_concurrency": max(1, min(args.concurrency, len(lines) or 1)),
    }
    Path(args.out, "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
