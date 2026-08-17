#!/usr/bin/env python3
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'missing patch anchor: {label}')
    return text.replace(old, new, 1)


def main() -> None:
    path = Path('.github/workflows/qwen-live-classification.yml')
    text = path.read_text(encoding='utf-8')

    # A code deployment must never kill already-running semantic workers. New
    # pushes queue behind the active pass and then pick up the newest runtime.
    text = replace_once(
        text,
        "  cancel-in-progress: ${{ github.event_name == 'push' }}",
        "  cancel-in-progress: false",
        'non-preemptive Qwen concurrency',
    )

    # Use short bounded passes everywhere, not only when the watchdog explicitly
    # dispatches one. Auto-continue preserves total throughput while artifacts are
    # published much sooner.
    text = text.replace("default: '240'", "default: '48'", 1)
    text = text.replace("${{ github.event.inputs.per_shard || '240' }}", "${{ github.event.inputs.per_shard || '48' }}", 1)
    text = text.replace("or 240)", "or 48)", 1)
    text = text.replace("except Exception: n=240", "except Exception: n=48", 1)

    # A sharding/freshness implementation change is part of Qwen runtime and
    # should schedule a new pass after (not instead of) the current one.
    if "      - 'pipeline/build_qwen_shadow_shards.py'" not in text:
        text = replace_once(
            text,
            "      - 'pipeline/build_qwen_dce_selection.py'\n",
            "      - 'pipeline/build_qwen_dce_selection.py'\n      - 'pipeline/build_qwen_shadow_shards.py'\n",
            'Qwen shadow-shard trigger path',
        )

    # Read the newest durable DCE attempt ledger at aggregate time. The workflow
    # checkout SHA can be older than DCE progress made while Qwen was classifying.
    old = """          git fetch origin main\n          git show origin/main:control/controller_state_checkpoint.json > latest-controller-state.json 2>/dev/null || printf '{}\\n' > latest-controller-state.json\n"""
    new = old + """          git show origin/main:control/dce_attempt_ledger.jsonl > latest-attempt-ledger.jsonl 2>/dev/null || : > latest-attempt-ledger.jsonl\n"""
    text = replace_once(text, old, new, 'fresh durable DCE attempt ledger')

    old_arg = """            --blocked-state latest-controller-state.json \\\n            --out qwen-live-selection.jsonl \\\n"""
    new_arg = """            --blocked-state latest-controller-state.json \\\n            --attempt-ledger latest-attempt-ledger.jsonl \\\n            --out qwen-live-selection.jsonl \\\n"""
    text = replace_once(text, old_arg, new_arg, 'selector attempt-ledger argument')

    path.write_text(text, encoding='utf-8')
    print('Qwen runtime safety applied: non-preemptive concurrency, 48-row passes, fresh attempt ledger.')


if __name__ == '__main__':
    main()
