#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
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


def family(name: str) -> str:
    n = name.casefold()
    if n == "init-release" or "wide-read" in n:
        return "orchestration"
    if n.startswith("cf-window"):
        return "UK_CONTRACTS_FINDER"
    if n.startswith("ie-pages"):
        return "IRELAND_ETENDERS"
    if n.startswith("official-"):
        return name[len("official-"):].upper()
    if "ted-discovery" in n:
        return "TED"
    return name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--novelty", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tender-discovery-runner-metrics/1.0",
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

    runner_seconds = 0.0
    failures = 0
    by_family = defaultdict(lambda: {"jobs": 0, "runner_seconds": 0.0, "failures": 0})
    timed = []
    for job in jobs:
        start = parse_ts(job.get("started_at"))
        end = parse_ts(job.get("completed_at"))
        seconds = max(0.0, (end - start).total_seconds()) if start and end else 0.0
        # GitHub matrix/orchestration jobs all consume hosted runners, so include
        # every timed job in the discovery cost denominator.
        runner_seconds += seconds
        conclusion = str(job.get("conclusion") or "")
        if conclusion not in {"success", "skipped", "neutral"}:
            failures += 1
        fam = family(str(job.get("name") or "unknown"))
        by_family[fam]["jobs"] += 1
        by_family[fam]["runner_seconds"] += seconds
        if conclusion not in {"success", "skipped", "neutral"}:
            by_family[fam]["failures"] += 1
        timed.append({"name": job.get("name"), "conclusion": conclusion, "runner_seconds": round(seconds, 3)})

    novelty = json.loads(Path(args.novelty).read_text(encoding="utf-8"))
    new_unique = int(novelty.get("new_vs_previous") or 0)
    minutes = runner_seconds / 60.0
    portal_novelty = novelty.get("portals") or {}
    family_metrics = {}
    for fam, rec in by_family.items():
        sec = float(rec["runner_seconds"])
        p = portal_novelty.get(fam) or {}
        new = int(p.get("new_vs_previous") or 0)
        family_metrics[fam] = {
            "jobs": rec["jobs"],
            "runner_minutes": round(sec / 60.0, 6),
            "failures": rec["failures"],
            "new_vs_previous": new,
            "new_unique_per_runner_minute": round(new / (sec / 60.0), 6) if sec > 0 else 0.0,
        }

    payload = {
        "contract": "DISCOVERY_RUNNER_EFFICIENCY_V1",
        "run_id": str(args.run_id),
        "jobs": len(jobs),
        "job_failures": failures,
        "runner_seconds_exact": round(runner_seconds, 3),
        "runner_minutes_exact": round(minutes, 6),
        "new_unique_vs_previous": new_unique,
        "new_unique_per_runner_minute_exact": round(new_unique / minutes, 6) if minutes > 0 else 0.0,
        "novelty_rate": novelty.get("novelty_rate"),
        "families": family_metrics,
        "job_timings": timed,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in payload.items() if k != "job_timings"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
