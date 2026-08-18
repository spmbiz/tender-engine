from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_matrix
import dce_batch_worker


def test_sam_is_supported_but_not_browser_portal():
    assert "US_SAM" in build_matrix.SUPPORTED
    assert "US_SAM_BULK" in build_matrix.SUPPORTED
    assert "US_SAM" not in build_matrix.BROWSER_PORTALS
    assert "US_SAM_BULK" not in build_matrix.BROWSER_PORTALS


def test_sam_gets_http_fast_lane_policy(monkeypatch):
    monkeypatch.setenv("DCE_HTTP_INLINE_RETRIES", "1")
    monkeypatch.setenv("DCE_HTTP_FAST_TIMEOUT_SECONDS", "90")
    # DCE V20 delegates the unchanged lane policy to the v19 compatibility
    # layer while adding HTTP probes around browser-capable work.
    retries, timeout, lane = dce_batch_worker.legacy._fast_lane_policy({"portal": "US_SAM"}, 2, 180)
    assert lane == "http_fast_lane"
    assert retries == 1
    assert timeout == 90
