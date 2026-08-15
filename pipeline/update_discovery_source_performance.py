#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--existing", default="")
    ap.add_argument("--efficiency", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--max-runs", type=int, default=8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    existing = load(args.existing)
    current = load(args.efficiency)
    run_id = str(args.run_id)
    history = list(existing.get("history") or [])
    history = [h for h in history if str(h.get("run_id")) != run_id]
    history.append({
        "run_id": run_id,
        "mode": current.get("discovery_mode"),
        "runner_minutes_exact": current.get("runner_minutes_exact"),
        "new_unique_vs_previous": current.get("new_unique_vs_previous"),
        "new_unique_per_runner_minute_exact": current.get("new_unique_per_runner_minute_exact"),
        "novelty_rate": current.get("novelty_rate"),
        "job_failures": current.get("job_failures"),
        "families": current.get("families") or {},
    })
    history = history[-max(1, args.max_runs):]

    names = sorted({name for h in history for name in (h.get("families") or {})})
    sources = {}
    for name in names:
        rows = [(h.get("families") or {}).get(name) for h in history]
        rows = [r for r in rows if isinstance(r, dict)]
        minutes = sum(float(r.get("runner_minutes") or 0) for r in rows)
        new = sum(int(r.get("new_vs_previous") or 0) for r in rows)
        failures = sum(int(r.get("failures") or 0) for r in rows)
        jobs = sum(int(r.get("jobs") or 0) for r in rows)
        positive_runs = sum(1 for r in rows if int(r.get("new_vs_previous") or 0) > 0)
        sources[name] = {
            "observations": len(rows),
            "jobs": jobs,
            "runner_minutes": round(minutes, 6),
            "new_unique": new,
            "new_unique_per_runner_minute": round(new / minutes, 6) if minutes > 0 else 0.0,
            "positive_run_rate": round(positive_runs / len(rows), 6) if rows else 0.0,
            "failures": failures,
            "scheduler_status": (
                "PROVEN" if len(rows) >= 2 and positive_runs >= 2
                else "WEAK" if len(rows) >= 3 and positive_runs == 0
                else "EXPLORATION"
            ),
        }

    payload = {
        "contract": "DISCOVERY_SOURCE_PERFORMANCE_V1",
        "run_ids": [str(h.get("run_id")) for h in history],
        "rolling_window": len(history),
        "sources": sources,
        "policy_note": "No source is permanently disabled by this state. Weak routes retain bounded exploration and daily deep reconcile coverage.",
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
