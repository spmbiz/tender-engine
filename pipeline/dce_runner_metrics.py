from __future__ import annotations

"""Measure exact GitHub-hosted runner wall time for a completed DCE Fanout run.

Global useful/runner-minute is exact for shard jobs: GitHub's started_at/completed_at
wall durations are summed once per shard runner. Per-portal runner-minute allocation
is explicitly marked as an estimate because current shards can mix portals; it is
apportioned by observed candidate-processing seconds from portal_yield.json.
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import requests


def parse_ts(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--portal-yield", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tender-dce-runner-metrics/1.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    jobs = []
    page = 1
    while True:
        r = requests.get(
            f"https://api.github.com/repos/{args.repo}/actions/runs/{args.run_id}/jobs",
            headers=headers,
            params={"per_page": 100, "page": page}, timeout=30,
        )
        r.raise_for_status()
        batch = r.json().get("jobs") or []
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    shard_jobs = [j for j in jobs if str(j.get("name") or "").startswith("shard-")]
    runner_seconds = 0.0
    timed = []
    shard_job_failures = 0
    for job in shard_jobs:
        start = parse_ts(job.get("started_at"))
        end = parse_ts(job.get("completed_at"))
        seconds = max(0.0, (end - start).total_seconds()) if start and end else 0.0
        runner_seconds += seconds
        conclusion = str(job.get("conclusion") or "")
        if conclusion not in {"success", "skipped", "neutral"}:
            shard_job_failures += 1
        timed.append({
            "job_id": job.get("id"),
            "name": job.get("name"),
            "conclusion": conclusion,
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "runner_seconds": round(seconds, 3),
        })

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    portal = json.loads(Path(args.portal_yield).read_text(encoding="utf-8"))
    useful = int(summary.get("gate_ready_substantive_dce") or 0)
    candidates = int(summary.get("candidates") or 0)
    candidate_failures = int(summary.get("worker_failures") or 0)
    runner_minutes = runner_seconds / 60.0

    total_processing = sum(max(0.0, float((v or {}).get("candidate_processing_seconds") or 0.0)) for v in portal.values())
    per_portal = {}
    for name, rec in portal.items():
        processing = max(0.0, float((rec or {}).get("candidate_processing_seconds") or 0.0))
        share = processing / total_processing if total_processing > 0 else 0.0
        estimated_runner_minutes = runner_minutes * share
        portal_useful = int((rec or {}).get("gate_ready_substantive_dce") or 0)
        per_portal[name] = {
            "estimated_runner_minutes": round(estimated_runner_minutes, 6),
            "runner_time_attribution": "estimated from candidate-processing-second share because shards currently mix portals",
            "gate_ready_substantive_dce": portal_useful,
            "estimated_useful_per_runner_minute": round(portal_useful / estimated_runner_minutes, 6) if estimated_runner_minutes > 0 else 0.0,
        }

    payload = {
        "run_id": str(args.run_id),
        "candidates": candidates,
        "shard_jobs": len(shard_jobs),
        "shard_jobs_with_timing": sum(1 for x in timed if x["runner_seconds"] > 0),
        "shard_job_failures": shard_job_failures,
        "shard_job_failure_rate": round(shard_job_failures / max(1, len(shard_jobs)), 6),
        "runner_seconds_exact": round(runner_seconds, 3),
        "runner_minutes_exact": round(runner_minutes, 6),
        "gate_ready_substantive_dce": useful,
        "useful_per_runner_minute_exact": round(useful / runner_minutes, 6) if runner_minutes > 0 else 0.0,
        "candidate_retryable_failures": candidate_failures,
        "candidate_retryable_failure_rate": round(candidate_failures / max(1, candidates), 6),
        "worker_failures": candidate_failures,
        "rate_limit_signals": int(summary.get("rate_limit_signals") or 0),
        "per_portal": per_portal,
        "jobs": timed,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "jobs"}, indent=2))


if __name__ == "__main__":
    main()
