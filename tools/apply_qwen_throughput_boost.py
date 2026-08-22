from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    """Validate the canonical Qwen throughput configuration without mutating it.

    This file used to patch workflow text from 192 -> 480 and could drift behind
    the real production workflow. The live configuration is now declarative in
    qwen-live-classification.yml and qwen_batch_runtime_config.json.
    """
    live = Path('.github/workflows/qwen-live-classification.yml').read_text(encoding='utf-8')
    runtime = json.loads(Path('control/qwen_batch_runtime_config.json').read_text(encoding='utf-8'))
    core = Path('pipeline/qwen_notice_batch_selfheal_core.py').read_text(encoding='utf-8')

    assert "default: '480'" in live
    assert "QWEN_OPERATIONAL_ROWS_PER_SHARD: '480'" in live
    assert "--timeout 30" in live
    assert "--description-chars 1200" in live
    assert "fallback=1" in live
    assert runtime.get('status') == 'PASS'
    champion = runtime.get('champion') or {}
    assert champion.get('safe_for_shadow_scale_out') is True
    assert int(champion.get('initial_batch_size') or 0) == 1
    assert 'synchronous_github_io_in_hot_path": False' in core

    print('Qwen throughput configuration validated: 480 rows/shard, singleton champion, no synchronous GitHub I/O in inference hot path.')


if __name__ == '__main__':
    main()
