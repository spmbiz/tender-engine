from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from build_matrix import BROWSER_PORTALS, resolve_dce_portal
import dce_batch_worker_v19 as legacy


RETRYABLE_STATUSES = legacy.RETRYABLE_STATUSES
RATE_LIMIT_RE = legacy.RATE_LIMIT_RE
ACTIVE_WORKER = "pipeline/dce_worker_v20.py"


def _probe_stage_root(out: str) -> Path:
    target = Path(out)
    return target.parent / f".{target.name}-http-probe-v20"


def _probe_manifest_is_success(manifest: dict) -> bool:
    return bool(
        isinstance(manifest, dict)
        and str(manifest.get("status") or "").upper() == "DOWNLOADED_PUBLIC"
        and isinstance(manifest.get("files"), list)
        and any(isinstance(row, dict) for row in manifest.get("files") or [])
    )


def _annotate_promoted_manifest(root: Path, probe_meta: dict) -> None:
    path = root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(manifest, dict):
            return
        manifest["scheduler_v20"] = {
            "phase": "HTTP_PROBE_PROMOTED",
            "browser_skipped": True,
            "probe_elapsed_seconds": probe_meta.get("elapsed_seconds"),
            "probe_timeout_seconds": probe_meta.get("timeout_seconds"),
            "probe_returncode": probe_meta.get("returncode"),
        }
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _run_http_probe(queue: str, line_no: int, out: str, timeout_seconds: int) -> dict:
    candidate = legacy.load_candidate(queue, line_no)
    candidate_id = str(candidate.get("candidate_id") or f"line-{line_no}")
    portal, raw_portal = resolve_dce_portal(candidate)
    slug = legacy.slugify(candidate_id)
    stage = _probe_stage_root(out)
    candidate_stage = stage / slug
    final_root = Path(out) / slug
    shutil.rmtree(candidate_stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DCE_HTTP_PROBE_ONLY"] = "1"
    cmd = [
        sys.executable,
        ACTIVE_WORKER,
        "--queue",
        queue,
        "--line",
        str(line_no),
        "--out",
        str(stage),
    ]
    t0 = time.monotonic()
    returncode = 0
    stdout = ""
    stderr = ""
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=max(3, int(timeout_seconds)),
            env=env,
        )
        returncode = proc.returncode
        stdout = proc.stdout[-6000:]
        stderr = proc.stderr[-6000:]
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        timed_out = True
        stdout = (exc.stdout or "")[-6000:] if isinstance(exc.stdout, str) else ""
        stderr = ((exc.stderr or "")[-6000:] if isinstance(exc.stderr, str) else "") + f"\nHTTP_PROBE_TIMEOUT_{timeout_seconds}s"
    elapsed = round(time.monotonic() - t0, 3)
    manifest = legacy.load_manifest(str(stage), candidate_id)
    success = _probe_manifest_is_success(manifest)

    rec = {
        "line": line_no,
        "candidate_id": candidate_id,
        "portal": portal,
        "raw_portal": raw_portal,
        "phase": "http_probe",
        "promoted": success,
        "status": str(manifest.get("status") or ("PROBE_TIMEOUT" if timed_out else "PROBE_MISS")),
        "files": len(manifest.get("files") or []) if isinstance(manifest, dict) else 0,
        "returncode": returncode,
        "elapsed_seconds": elapsed,
        "timeout_seconds": max(3, int(timeout_seconds)),
        "stdout": stdout,
        "stderr": stderr,
    }

    if success and candidate_stage.exists():
        shutil.rmtree(final_root, ignore_errors=True)
        final_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(candidate_stage), str(final_root))
        _annotate_promoted_manifest(final_root, rec)
        rec["result"] = {
            "line": line_no,
            "candidate_id": candidate_id,
            "portal": portal,
            "raw_portal": raw_portal,
            "lane": "http_probe_promoted",
            "returncode": 0,
            "status": "DOWNLOADED_PUBLIC",
            "attempt_count": 1,
            "retries": 0,
            "requested_retries": 0,
            "effective_retries": 0,
            "requested_timeout_seconds": max(3, int(timeout_seconds)),
            "effective_timeout_seconds": max(3, int(timeout_seconds)),
            "rate_limited": bool(RATE_LIMIT_RE.search("\n".join([stderr, str(manifest.get("error") or "")]))) if isinstance(manifest, dict) else False,
            "elapsed_seconds": elapsed,
            "attempts": [{
                "attempt": 1,
                "phase": "http_probe",
                "returncode": returncode,
                "status": "DOWNLOADED_PUBLIC",
                "elapsed_seconds": elapsed,
                "rate_limited": False,
                "stdout": stdout,
                "stderr": stderr,
            }],
        }
    else:
        shutil.rmtree(candidate_stage, ignore_errors=True)
        rec["result"] = None
    return rec


def _run_full(queue: str, line_no: int, out: str, retries: int, timeout_seconds: int) -> dict:
    candidate = legacy.load_candidate(queue, line_no)
    candidate_id = str(candidate.get("candidate_id") or f"line-{line_no}")
    portal, raw_portal = resolve_dce_portal(candidate)
    effective_retries, effective_timeout, lane = legacy._fast_lane_policy(candidate, retries, timeout_seconds)
    attempts = []
    started = time.monotonic()

    for attempt in range(1, effective_retries + 2):
        cmd = [
            sys.executable,
            ACTIVE_WORKER,
            "--queue",
            queue,
            "--line",
            str(line_no),
            "--out",
            out,
        ]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=effective_timeout)
            returncode = proc.returncode
            stdout = proc.stdout[-12000:]
            stderr = proc.stderr[-12000:]
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else ""
            stderr = ((exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else "") + f"\nWORKER_TIMEOUT_{effective_timeout}s"

        manifest = legacy.load_manifest(out, candidate_id)
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
        if not retryable or attempt > effective_retries:
            break
        time.sleep(min(4.0, 0.75 * attempt + random.random()))

    final = attempts[-1]
    return {
        "line": line_no,
        "candidate_id": candidate_id,
        "portal": portal,
        "raw_portal": raw_portal,
        "lane": lane,
        "returncode": final["returncode"],
        "status": final["status"],
        "attempt_count": len(attempts),
        "retries": max(0, len(attempts) - 1),
        "requested_retries": max(0, retries),
        "effective_retries": effective_retries,
        "requested_timeout_seconds": max(30, timeout_seconds),
        "effective_timeout_seconds": effective_timeout,
        "rate_limited": any(a["rate_limited"] for a in attempts),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "attempts": attempts,
    }


def _print_result(rec: dict) -> None:
    print(json.dumps({k: rec[k] for k in rec if k != "attempts"}, ensure_ascii=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--lines", required=True, help="comma-separated 1-based queue lines")
    ap.add_argument("--out", default="out")
    ap.add_argument("--concurrency", type=int, default=int(os.getenv("DCE_LOCAL_CONCURRENCY", "2")))
    ap.add_argument(
        "--http-concurrency",
        type=int,
        default=int(os.getenv("DCE_HTTP_LOCAL_CONCURRENCY", "6")),
        help="independent native HTTP worker limit",
    )
    ap.add_argument(
        "--placsp-concurrency",
        type=int,
        default=int(os.getenv("DCE_PLACSP_LOCAL_CONCURRENCY", "3")),
        help="bounded PLACSP subprocess concurrency",
    )
    ap.add_argument(
        "--http-probe-concurrency",
        type=int,
        default=int(os.getenv("DCE_HTTP_PROBE_CONCURRENCY", "12")),
        help="parallel HTTP-only probes for browser-capable candidates",
    )
    ap.add_argument(
        "--http-probe-timeout-seconds",
        type=int,
        default=int(os.getenv("DCE_HTTP_PROBE_TIMEOUT_SECONDS", "5")),
        help="hard per-candidate preflight budget before browser fallback",
    )
    ap.add_argument("--retries", type=int, default=int(os.getenv("DCE_ITEM_RETRIES", "1")))
    ap.add_argument("--timeout-seconds", type=int, default=int(os.getenv("DCE_ITEM_TIMEOUT_SECONDS", "150")))
    args = ap.parse_args()

    lines = [int(x.strip()) for x in args.lines.split(",") if x.strip()]
    Path(args.out).mkdir(parents=True, exist_ok=True)
    stage_root = _probe_stage_root(args.out)
    shutil.rmtree(stage_root, ignore_errors=True)
    results: list[dict] = []
    probe_records: list[dict] = []
    wall_start = time.monotonic()

    lane_lines = {"http_fast_lane": [], "browser_fast_lane": [], "placsp_http_lane": []}
    for line in lines:
        candidate = legacy.load_candidate(args.queue, line)
        portal, _ = resolve_dce_portal(candidate)
        lane = legacy._fast_lane_policy(candidate, max(0, args.retries), max(30, args.timeout_seconds))[2]
        if lane == "http_fast_lane" and portal == "ES_PLACSP":
            lane_lines["placsp_http_lane"].append(line)
        else:
            lane_lines[lane].append(line)

    browser_workers = max(1, min(args.concurrency, len(lane_lines["browser_fast_lane"]) or 1))
    http_workers = max(1, min(args.http_concurrency, len(lane_lines["http_fast_lane"]) or 1))
    placsp_workers = max(1, min(args.placsp_concurrency, len(lane_lines["placsp_http_lane"]) or 1))
    probe_workers = max(1, min(args.http_probe_concurrency, len(lane_lines["browser_fast_lane"]) or 1))

    pools: list[ThreadPoolExecutor] = []
    native_futures = []
    browser_futures = []
    try:
        browser_pool = None
        if lane_lines["browser_fast_lane"]:
            browser_pool = ThreadPoolExecutor(max_workers=browser_workers)
            pools.append(browser_pool)

        if lane_lines["http_fast_lane"]:
            http_pool = ThreadPoolExecutor(max_workers=http_workers)
            pools.append(http_pool)
            for line in lane_lines["http_fast_lane"]:
                native_futures.append(http_pool.submit(_run_full, args.queue, line, args.out, max(0, args.retries), max(30, args.timeout_seconds)))

        if lane_lines["placsp_http_lane"]:
            placsp_pool = ThreadPoolExecutor(max_workers=placsp_workers)
            pools.append(placsp_pool)
            for line in lane_lines["placsp_http_lane"]:
                native_futures.append(placsp_pool.submit(_run_full, args.queue, line, args.out, max(0, args.retries), max(30, args.timeout_seconds)))

        if lane_lines["browser_fast_lane"]:
            probe_pool = ThreadPoolExecutor(max_workers=probe_workers)
            pools.append(probe_pool)
            probe_futures = {
                probe_pool.submit(_run_http_probe, args.queue, line, args.out, max(3, args.http_probe_timeout_seconds)): line
                for line in lane_lines["browser_fast_lane"]
            }
            for fut in as_completed(probe_futures):
                line = probe_futures[fut]
                try:
                    probe = fut.result()
                except Exception as exc:
                    probe = {
                        "line": line,
                        "phase": "http_probe",
                        "promoted": False,
                        "status": "PROBE_EXCEPTION",
                        "files": 0,
                        "returncode": 98,
                        "elapsed_seconds": 0,
                        "timeout_seconds": max(3, args.http_probe_timeout_seconds),
                        "stdout": "",
                        "stderr": repr(exc),
                        "result": None,
                    }
                probe_records.append(probe)
                print(json.dumps({k: probe.get(k) for k in ("line", "phase", "promoted", "status", "files", "elapsed_seconds", "timeout_seconds")}, ensure_ascii=False), flush=True)
                if probe.get("result"):
                    results.append(probe["result"])
                    _print_result(probe["result"])
                elif browser_pool is not None:
                    browser_futures.append(
                        browser_pool.submit(_run_full, args.queue, line, args.out, max(0, args.retries), max(30, args.timeout_seconds))
                    )

        for fut in as_completed(native_futures + browser_futures):
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {
                    "line": None,
                    "candidate_id": None,
                    "portal": None,
                    "raw_portal": None,
                    "lane": None,
                    "returncode": 99,
                    "status": "BATCH_EXCEPTION",
                    "attempt_count": 1,
                    "retries": 0,
                    "rate_limited": False,
                    "elapsed_seconds": 0,
                    "attempts": [{"attempt": 1, "error": repr(exc)}],
                }
            results.append(rec)
            _print_result(rec)
    finally:
        for pool in pools:
            pool.shutdown(wait=True)
        shutil.rmtree(stage_root, ignore_errors=True)

    results.sort(key=lambda r: (10**9 if r.get("line") is None else int(r["line"])))
    Path(args.out, "batch_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    promoted = sum(1 for r in probe_records if r.get("promoted"))
    fallbacks = len(probe_records) - promoted
    summary = {
        "lines": lines,
        "results": len(results),
        "failures": sum(1 for r in results if r.get("returncode") != 0),
        "retryable_final": sum(1 for r in results if r.get("status") in RETRYABLE_STATUSES),
        "retries": sum(int(r.get("retries") or 0) for r in results),
        "rate_limited": sum(1 for r in results if r.get("rate_limited")),
        "wall_seconds": round(time.monotonic() - wall_start, 3),
        "local_concurrency": browser_workers,
        "browser_concurrency": browser_workers,
        "http_concurrency": http_workers,
        "placsp_concurrency": placsp_workers,
        "http_probe_concurrency": probe_workers,
        "http_probe_timeout_seconds": max(3, args.http_probe_timeout_seconds),
        "http_probe_attempted": len(probe_records),
        "http_probe_promoted": promoted,
        "browser_fallback": fallbacks,
        "http_probe_hit_rate": round(promoted / len(probe_records), 4) if probe_records else 0.0,
        "http_probe_candidate_seconds": round(sum(float(r.get("elapsed_seconds") or 0) for r in probe_records), 3),
        "lane_counts": dict(Counter(r.get("lane") for r in results if r.get("lane"))),
        "scheduler_counts": {
            "native_http": len(lane_lines["http_fast_lane"]),
            "placsp_http": len(lane_lines["placsp_http_lane"]),
            "http_probe_candidates": len(lane_lines["browser_fast_lane"]),
            "http_probe_promoted": promoted,
            "browser_fallback": fallbacks,
        },
    }
    Path(args.out, "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.out, "http_probe_summary.json").write_text(
        json.dumps([{k: v for k, v in row.items() if k not in {"stdout", "stderr", "result"}} for row in probe_records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
