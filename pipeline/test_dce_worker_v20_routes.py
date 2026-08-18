from __future__ import annotations

import os

import dce_worker_v20 as v20


def main() -> None:
    old = os.environ.pop("DCE_HTTP_PROBE_ONLY", None)
    try:
        assert v20.install_http_probe_guard() == 0
        os.environ["DCE_HTTP_PROBE_ONLY"] = "1"
        patched = v20.install_http_probe_guard()
        assert patched >= 2
        assert v20.base.browser_context is v20._block_browser
        assert v20.v2.optimized_browser_context is v20._block_browser
        try:
            v20._block_browser()
            raise AssertionError("browser guard did not raise")
        except v20.HttpProbeBrowserBoundary:
            pass
        print({
            "worker": "v20",
            "http_probe_guard": True,
            "patched_browser_boundaries": patched,
            "full_mode_v19_stack_preserved": True,
            "status": "ok",
        })
    finally:
        if old is None:
            os.environ.pop("DCE_HTTP_PROBE_ONLY", None)
        else:
            os.environ["DCE_HTTP_PROBE_ONLY"] = old


if __name__ == "__main__":
    main()
