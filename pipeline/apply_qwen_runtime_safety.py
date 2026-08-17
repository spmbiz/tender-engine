#!/usr/bin/env python3
from pathlib import Path

# This file is intentionally trigger-scoped: updates re-run the one-shot runtime
# patch with the latest safety rules while the patch workflow uses a shallow clone.


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'missing patch anchor: {label}')
    return text.replace(old, new, 1)


def main() -> None:
    path = Path('.github/workflows/qwen-live-classification.yml')
    text = path.read_text(encoding='utf-8')

    text = replace_once(
        text,
        "  cancel-in-progress: ${{ github.event_name == 'push' }}",
        "  cancel-in-progress: false",
        'non-preemptive Qwen concurrency',
    )

    text = text.replace("default: '240'", "default: '48'", 1)
    text = text.replace("${{ github.event.inputs.per_shard || '240' }}", "${{ github.event.inputs.per_shard || '48' }}", 1)
    text = text.replace("or 240)", "or 48)", 1)
    text = text.replace("except Exception: n=240", "except Exception: n=48", 1)

    if "      - 'pipeline/build_qwen_shadow_shards.py'" not in text:
        text = replace_once(
            text,
            "      - 'pipeline/build_qwen_dce_selection.py'\n",
            "      - 'pipeline/build_qwen_dce_selection.py'\n      - 'pipeline/build_qwen_shadow_shards.py'\n",
            'Qwen shadow-shard trigger path',
        )

    old = """          git fetch origin main\n          git show origin/main:control/controller_state_checkpoint.json > latest-controller-state.json 2>/dev/null || printf '{}\\n' > latest-controller-state.json\n"""
    new = old + """          git show origin/main:control/dce_attempt_ledger.jsonl > latest-attempt-ledger.jsonl 2>/dev/null || : > latest-attempt-ledger.jsonl\n"""
    text = replace_once(text, old, new, 'fresh durable DCE attempt ledger')

    old_arg = """            --blocked-state latest-controller-state.json \\\n            --out qwen-live-selection.jsonl \\\n"""
    new_arg = """            --blocked-state latest-controller-state.json \\\n            --attempt-ledger latest-attempt-ledger.jsonl \\\n            --out qwen-live-selection.jsonl \\\n"""
    text = replace_once(text, old_arg, new_arg, 'selector attempt-ledger argument')

    old_persist = '''      - name: Persist current Qwen DCE selection for DCE Fanout V2
        if: steps.selection.outputs.count != '0'
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p queues control/qwen_live
          cp qwen-live-selection.jsonl queues/qwen_live_selection_latest.jsonl
          cp qwen-live-selection.summary.json control/qwen_live/selection_summary.json
          cp publish/qwen-classification-merge-summary-latest.json control/qwen_live/classification_summary.json
          git config user.name 'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          git add queues/qwen_live_selection_latest.jsonl control/qwen_live/
          git commit -m "qwen: publish live semantic DCE lane ${GITHUB_RUN_ID}" || true
          for attempt in 1 2 3 4 5; do
            if git pull --rebase origin main && git push origin HEAD:main; then exit 0; fi
            git rebase --abort >/dev/null 2>&1 || true
            sleep "$((attempt * 4))"
          done
          exit 1
'''
    new_persist = '''      - name: Persist current Qwen DCE selection for DCE Fanout V2
        if: steps.selection.outputs.count != '0'
        shell: bash
        run: |
          set -euo pipefail
          cp qwen-live-selection.jsonl /tmp/qwen-live-selection.jsonl
          cp qwen-live-selection.summary.json /tmp/qwen-live-selection.summary.json
          cp publish/qwen-classification-merge-summary-latest.json /tmp/qwen-classification-summary.json
          git config user.name 'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          for attempt in 1 2 3 4 5; do
            git fetch origin main
            git reset --hard origin/main
            mkdir -p queues control/qwen_live
            cp /tmp/qwen-live-selection.jsonl queues/qwen_live_selection_latest.jsonl
            cp /tmp/qwen-live-selection.summary.json control/qwen_live/selection_summary.json
            cp /tmp/qwen-classification-summary.json control/qwen_live/classification_summary.json
            git add queues/qwen_live_selection_latest.jsonl control/qwen_live/
            if git diff --cached --quiet; then
              echo 'Semantic DCE queue already current.'
              exit 0
            fi
            git commit -m "qwen: publish live semantic DCE lane ${GITHUB_RUN_ID}"
            if git push origin HEAD:main; then exit 0; fi
            sleep "$((attempt * 3))"
          done
          exit 1
'''
    text = replace_once(text, old_persist, new_persist, 'race-safe generated queue publication')

    path.write_text(text, encoding='utf-8')
    print('Qwen runtime safety applied: non-preemptive concurrency, 48-row passes, fresh attempt ledger, race-safe queue publication.')


if __name__ == '__main__':
    main()
