from __future__ import annotations

from pathlib import Path


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing marker for {label}: {old!r}")
    return text.replace(old, new, 1)


def main() -> None:
    live_path = Path('.github/workflows/qwen-live-classification.yml')
    drain_path = Path('.github/workflows/qwen-live-recovery-drainer.yml')

    live = live_path.read_text(encoding='utf-8')
    live = replace_required(live, "default: '192'", "default: '480'", 'qwen per_shard workflow input default')
    live = replace_required(
        live,
        "REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '192' }}",
        "REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '480' }}",
        'qwen per_shard env fallback',
    )
    live = replace_required(
        live,
        "try: n=int(os.environ.get('REQUESTED_PER_SHARD') or 192)",
        "try: n=int(os.environ.get('REQUESTED_PER_SHARD') or 480)",
        'qwen per_shard parser fallback',
    )
    live = replace_required(live, "except Exception: n=192", "except Exception: n=480", 'qwen per_shard exception fallback')
    live = replace_required(live, "- cron: '43 */6 * * *'", "- cron: '43 * * * *'", 'qwen hourly safety schedule')
    live_path.write_text(live, encoding='utf-8')

    drain = drain_path.read_text(encoding='utf-8')
    drain = replace_required(drain, "-f per_shard=192", "-f per_shard=480", 'qwen recovery continuation wave size')

    old_dce = '''          dce_parallel="$(python - <<'PY'\n          from pipeline.global_admission import dynamic_tender_parallel\n          allowed,_=dynamic_tender_parallel(10)\n          print(max(0,min(10,int(allowed))))\n          PY\n          )"'''
    new_dce = '''          dce_parallel="$(QWEN_REMAINING='${{ steps.rebuild.outputs.remaining }}' python - <<'PY'\n          import os\n          from pipeline.global_admission import dynamic_tender_parallel\n          remaining=max(0,int(os.environ.get('QWEN_REMAINING') or 0))\n          # During the one-time semantic backfill, classification is the scarce\n          # stage. Keep DCE moving, but reserve most Tender capacity for Qwen.\n          if remaining >= 50000:\n              requested=2\n          elif remaining >= 20000:\n              requested=4\n          elif remaining >= 5000:\n              requested=6\n          else:\n              requested=10\n          allowed,_=dynamic_tender_parallel(requested)\n          print(max(0,min(requested,int(allowed))))\n          PY\n          )"'''
    drain = replace_required(drain, old_dce, new_dce, 'backlog-aware DCE capacity')
    drain_path.write_text(drain, encoding='utf-8')

    # Fail closed if the intended safety properties disappeared while patching.
    assert "QWEN_WORKERS_REQUESTED: '20'" in live
    assert "--max-runtime-seconds 7800" in live
    assert "cancel-in-progress: false" in live
    assert "-f per_shard=480" in drain
    assert "remaining >= 50000" in drain and "requested=2" in drain
    print('Qwen throughput boost applied: per_shard=480, hourly fallback, backlog-aware DCE throttling.')


if __name__ == '__main__':
    main()
