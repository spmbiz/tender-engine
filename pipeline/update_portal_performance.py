from __future__ import annotations

"""Maintain bounded rolling DCE source performance for the selector.

The state is small mutable scheduler state. Immutable per-run evidence remains in
DCE harvest Releases. Runs are de-duplicated by DCE run id and only the most recent
N samples are retained so one outage or ancient adapter behavior cannot dominate
forever.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load(path: str | None, default):
    if not path:
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def run_entry(run_id: str, portal_yield: dict, runner_yield: dict | None) -> dict:
    portals = {}
    for portal, rec in sorted((portal_yield or {}).items()):
        if not isinstance(rec, dict):
            continue
        candidates = int(rec.get("candidates") or 0)
        useful = int(rec.get("gate_ready_substantive_dce") or 0)
        auth = int(rec.get("auth_required") or 0)
        generic = int(rec.get("generic_or_unresolved") or 0)
        portals[str(portal).upper()] = {
            "candidates": candidates,
            "useful_final": useful,
            "auth_required": auth,
            "generic_or_unresolved": generic,
            "candidate_processing_seconds": round(float(rec.get("candidate_processing_seconds") or 0.0), 3),
            "retries": int(rec.get("retries") or 0),
            "rate_limit_signals": int(rec.get("rate_limit_signals") or 0),
            "worker_failures": int(rec.get("worker_failures") or 0),
        }
    return {
        "run_id": str(run_id),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "runner_minutes_exact": float((runner_yield or {}).get("runner_minutes_exact") or 0.0),
        "useful_per_runner_minute_exact": float((runner_yield or {}).get("useful_per_runner_minute_exact") or 0.0),
        "portals": portals,
    }


def aggregate(runs: list[dict]) -> dict:
    acc: dict[str, dict] = {}
    for run in runs:
        for portal, rec in (run.get("portals") or {}).items():
            s = acc.setdefault(portal, {
                "observed_runs": 0,
                "candidates": 0,
                "useful_final": 0,
                "auth_required": 0,
                "generic_or_unresolved": 0,
                "candidate_processing_seconds": 0.0,
                "retries": 0,
                "rate_limit_signals": 0,
                "worker_failures": 0,
            })
            s["observed_runs"] += 1
            for key in ("candidates", "useful_final", "auth_required", "generic_or_unresolved", "retries", "rate_limit_signals", "worker_failures"):
                s[key] += int(rec.get(key) or 0)
            s["candidate_processing_seconds"] += float(rec.get("candidate_processing_seconds") or 0.0)

    out = {}
    for portal, s in sorted(acc.items()):
        n = int(s["candidates"])
        useful = int(s["useful_final"])
        auth = int(s["auth_required"])
        generic = int(s["generic_or_unresolved"])
        processing_minutes = float(s["candidate_processing_seconds"]) / 60.0
        # Conservative Beta-like prior: 2 useful out of 10 pseudo-observations.
        # It prevents tiny 1/1 sources from outranking a proven 98/160 route.
        smoothed = (useful + 2.0) / (n + 10.0) if n >= 0 else 0.2
        out[portal] = {
            **s,
            "candidate_processing_seconds": round(float(s["candidate_processing_seconds"]), 3),
            "candidate_processing_minutes": round(processing_minutes, 6),
            "empirical_useful_rate": round(useful / n, 6) if n else 0.0,
            "smoothed_useful_rate": round(smoothed, 6),
            "auth_rate": round(auth / n, 6) if n else 0.0,
            "generic_or_unresolved_rate": round(generic / n, 6) if n else 0.0,
            "useful_per_candidate_processing_minute": round(useful / processing_minutes, 6) if processing_minutes > 0 else 0.0,
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--existing", default="")
    ap.add_argument("--portal-yield", required=True)
    ap.add_argument("--runner-yield", default="")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--max-runs", type=int, default=8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    state = load(args.existing, {})
    runs = [x for x in (state.get("runs") or []) if isinstance(x, dict) and str(x.get("run_id")) != str(args.run_id)]
    portals = load(args.portal_yield, {})
    runner = load(args.runner_yield, {}) if args.runner_yield else {}
    runs.append(run_entry(args.run_id, portals, runner))
    runs = runs[-max(1, int(args.max_runs)):]

    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "window_max_runs": max(1, int(args.max_runs)),
        "run_ids": [str(x.get("run_id")) for x in runs],
        "runs": runs,
        "portals": aggregate(runs),
        "policy_note": "Bounded rolling source performance for retrieval scheduling only; never a tender eligibility/final verdict signal.",
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"run_ids": payload["run_ids"], "portals": payload["portals"]}, indent=2))


if __name__ == "__main__":
    main()
