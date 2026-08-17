#!/usr/bin/env python3
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'missing patch anchor: {label}')
    return text.replace(old, new, 1)


def main() -> None:
    dce_path = Path('.github/workflows/dce-fanout-v2.yml')
    dce = dce_path.read_text(encoding='utf-8')
    anchor = '''          python pipeline/publish_supergreen_hot.py \\\n            --review fast-adjudication/adjudication.jsonl \\\n            --run-id "$RUN_ID" \\\n            --shard "$SHARD_ID" \\\n            --repo "$REPO"\n'''
    patched = anchor + '''          # GitHub deliberately suppresses push-triggered workflows for commits made\n          # with GITHUB_TOKEN. Dispatch explicitly after every completed DCE shard so\n          # the user-facing inbox follows shard-hot evidence in seconds, not at the\n          # end of the whole DCE wave. Concurrency on the refresh workflow coalesces\n          # bursts safely; the latest refresh always reads the latest hot bank.\n          gh workflow run gpt-inbox-live-refresh.yml --ref main\n'''
    dce = replace_once(dce, anchor, patched, 'per-shard inbox dispatch')
    dce_path.write_text(dce, encoding='utf-8')

    qwen_path = Path('.github/workflows/qwen-live-classification.yml')
    qwen = qwen_path.read_text(encoding='utf-8')
    # 240-row workers routinely take far too long before producing their first
    # artifact. Keep total throughput by auto-continuing many short passes; publish
    # 48-row shard artifacts quickly so the incremental conveyor can merge them as
    # soon as each worker finishes.
    qwen = qwen.replace("default: '240'", "default: '48'", 1)
    qwen = qwen.replace("${{ github.event.inputs.per_shard || '240' }}", "${{ github.event.inputs.per_shard || '48' }}", 1)
    qwen = qwen.replace("or 240)", "or 48)", 1)
    qwen = qwen.replace("except Exception: n=240", "except Exception: n=48", 1)

    old = """          git fetch origin main\n          git show origin/main:control/controller_state_checkpoint.json > latest-controller-state.json 2>/dev/null || printf '{}\\n' > latest-controller-state.json\n"""
    new = old + """          git show origin/main:control/dce_attempt_ledger.jsonl > latest-attempt-ledger.jsonl 2>/dev/null || : > latest-attempt-ledger.jsonl\n"""
    qwen = replace_once(qwen, old, new, 'fresh durable attempt ledger')
    oldarg = """            --blocked-state latest-controller-state.json \\\n            --out qwen-live-selection.jsonl \\\n"""
    newarg = """            --blocked-state latest-controller-state.json \\\n            --attempt-ledger latest-attempt-ledger.jsonl \\\n            --out qwen-live-selection.jsonl \\\n"""
    qwen = replace_once(qwen, oldarg, newarg, 'selector exact-attempt ledger arg')
    qwen_path.write_text(qwen, encoding='utf-8')

    print('realtime conveyor patch applied')


if __name__ == '__main__':
    main()
