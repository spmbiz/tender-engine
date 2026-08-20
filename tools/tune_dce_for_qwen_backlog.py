#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / 'control/qwen_live/classification_summary.json'
DESIRED = ROOT / 'control/desired_state.json'


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def policy(remaining: int) -> tuple[int, int, str]:
    if remaining >= 50_000:
        return 4, 2, 'qwen_backfill_guarded_thin_dce'
    if remaining >= 20_000:
        return 20, 4, 'qwen_backfill_dce_low'
    if remaining >= 5_000:
        return 80, 8, 'qwen_backfill_dce_medium'
    return 320, 20, 'deep_queue_streaming_hotpath'


def main() -> None:
    summary = load(SUMMARY)
    desired = load(DESIRED)
    remaining = max(0, int(summary.get('remaining_classification_queue') or 0))
    max_candidates, expected_slots, mode = policy(remaining)

    dce = desired.setdefault('dce', {})
    latency = dce.setdefault('latency_policy', {})
    benchmark = dce.setdefault('benchmark_basis', {})
    changed = False

    updates = {
        'max_candidates_per_cycle': max_candidates,
    }
    for key, value in updates.items():
        if dce.get(key) != value:
            dce[key] = value
            changed = True

    latency_updates = {
        'target_candidates_per_batch': max_candidates,
        'expected_github_parallel_slots': expected_slots,
        'mode': mode,
        'goal': (
            'prioritize Qwen semantic backfill while preserving a bounded continuous DCE lane; '
            'automatically restore deeper DCE throughput as classification backlog falls'
            if remaining >= 5_000
            else 'maximize guarded or ChatGPT-ready supergreen candidates per runner-minute: keep a deep ranked DCE reservoir queued, use short route-aware shards, fail fast on blocking routes, and publish each shard before the canonical batch aggregate completes'
        ),
    }
    for key, value in latency_updates.items():
        if latency.get(key) != value:
            latency[key] = value
            changed = True

    decision = f'auto_qwen_backlog_{remaining}_dce_candidates_{max_candidates}'
    if benchmark.get('decision') != decision:
        benchmark['decision'] = decision
        changed = True

    if changed:
        DESIRED.write_text(json.dumps(desired, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    print(json.dumps({
        'remaining_classification_queue': remaining,
        'max_candidates_per_cycle': max_candidates,
        'expected_github_parallel_slots': expected_slots,
        'mode': mode,
        'changed': changed,
    }, indent=2))


if __name__ == '__main__':
    main()
