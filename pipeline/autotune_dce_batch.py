#!/usr/bin/env python3
from __future__ import annotations

"""Evidence-based DCE batch size tuner.

One variable at a time: candidate batch size. The tuner never changes DCE
eligibility, portal weights, or local concurrency. It compares exact useful DCE
per GitHub runner-minute against the last accepted benchmark and either keeps,
rolls back, or advances one rung after a successful benchmark.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

LADDER = [320, 640, 1000]
MIN_KEEP_RATIO = 0.92
MIN_ADVANCE_RATIO = 0.97
MAX_FAILURE_RATE = 0.01
MAX_RATE_LIMIT_SIGNALS = 0


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desired", default="control/desired_state.json")
    ap.add_argument("--runner-yield", required=True)
    ap.add_argument("--out", default="control/desired_state.json")
    ap.add_argument("--decision-out", default="dce-batch-autotune.json")
    args = ap.parse_args()

    desired = load(Path(args.desired))
    metrics = load(Path(args.runner_yield))
    dce = desired.setdefault("dce", {})
    current = int(dce.get("max_candidates_per_cycle") or 320)
    current_yield = float(metrics.get("useful_per_runner_minute_exact") or 0.0)
    useful = int(metrics.get("gate_ready_substantive_dce") or metrics.get("gate_ready") or 0)
    runner_minutes = float(metrics.get("runner_minutes_exact") or 0.0)
    failures = int(metrics.get("worker_failures") or 0)
    rate_limits = int(metrics.get("rate_limit_signals") or 0)
    shard_jobs = max(1, int(metrics.get("shard_jobs") or 1))
    failure_rate = failures / shard_jobs

    basis = dce.get("benchmark_basis") or {}
    reference_size = int(basis.get("previous_batch_candidates") or 0)
    reference_yield = float(basis.get("previous_useful_per_runner_minute_exact") or 0.0)
    if not reference_yield:
        reference_yield = current_yield
        reference_size = current

    ratio = current_yield / reference_yield if reference_yield > 0 else 0.0
    healthy = (
        useful > 0
        and runner_minutes > 0
        and failure_rate <= MAX_FAILURE_RATE
        and rate_limits <= MAX_RATE_LIMIT_SIGNALS
    )

    action = "KEEP"
    next_size = current
    reason = "benchmark neutral/healthy"

    if not healthy or ratio < MIN_KEEP_RATIO:
        # Return to the last accepted benchmark rung whenever it is a valid lower
        # rung. Never promote the failed observation to the new reference.
        if reference_size in LADDER and reference_size < current:
            next_size = reference_size
        else:
            lower = [x for x in LADDER if x < current]
            next_size = max(lower) if lower else current
        action = "ROLLBACK" if next_size < current else "KEEP"
        reason = f"unhealthy or yield ratio {ratio:.3f} below keep floor {MIN_KEEP_RATIO:.2f}"
    elif current in LADDER and ratio >= MIN_ADVANCE_RATIO:
        higher = [x for x in LADDER if x > current]
        if higher:
            next_size = min(higher)
            action = "ADVANCE"
            reason = f"healthy exact yield ratio {ratio:.3f} >= advance floor {MIN_ADVANCE_RATIO:.2f}"
        else:
            reason = "top tested batch-size rung reached"

    decision = {
        "contract": "DCE_BATCH_AUTOTUNE_V2",
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "current_batch_size": current,
        "next_batch_size": next_size,
        "reference_batch_size": reference_size,
        "reference_useful_per_runner_minute": reference_yield,
        "observed_useful_per_runner_minute": current_yield,
        "yield_ratio": round(ratio, 6),
        "gate_ready_substantive_dce": useful,
        "runner_minutes_exact": runner_minutes,
        "worker_failure_rate": round(failure_rate, 6),
        "rate_limit_signals": rate_limits,
        "reason": reason,
    }

    if action == "ADVANCE":
        # A healthy current rung becomes the accepted baseline for testing the
        # next rung.
        dce["max_candidates_per_cycle"] = next_size
        dce["benchmark_basis"] = {
            "previous_batch_candidates": current,
            "previous_batch_gate_ready": useful,
            "previous_runner_minutes_exact": runner_minutes,
            "previous_useful_per_runner_minute_exact": current_yield,
            "decision": f"autotune_advance_to_{next_size}",
        }
    elif action == "ROLLBACK":
        dce["max_candidates_per_cycle"] = next_size
        # Keep the last accepted reference exactly as-is. The failed larger rung
        # is recorded only in the immutable autotune decision, never as baseline.
        dce["benchmark_basis"] = basis
    else:
        dce.setdefault("benchmark_basis", basis)

    Path(args.out).write_text(json.dumps(desired, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.decision_out).write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
