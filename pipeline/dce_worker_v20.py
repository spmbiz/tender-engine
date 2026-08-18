from __future__ import annotations

import os
import sys

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v19 as v19  # register the complete validated V19 stack


class HttpProbeBrowserBoundary(RuntimeError):
    """Raised when an HTTP-only preflight reaches a browser boundary."""


def _block_browser(*_args, **_kwargs):
    raise HttpProbeBrowserBoundary("DCE_HTTP_PROBE_ONLY_BROWSER_BOUNDARY")


def install_http_probe_guard() -> int:
    """Prevent any Playwright launch during a scheduler HTTP preflight.

    V19 and its historical adapter modules reference browser helpers in a few
    different ways (base helper, optimized helper, imported sync_playwright).
    Patch the already-loaded worker modules plus playwright.sync_api itself so the
    preflight can safely exercise the exact same HTTP-first adapter stack and stop
    immediately when a browser would otherwise be required.
    """
    if str(os.getenv("DCE_HTTP_PROBE_ONLY") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return 0

    patched = 0
    for name, module in list(sys.modules.items()):
        if not name.startswith("dce_worker") or module is None:
            continue
        for attr in ("browser_context", "optimized_browser_context", "sync_playwright"):
            if hasattr(module, attr):
                try:
                    setattr(module, attr, _block_browser)
                    patched += 1
                except Exception:
                    pass

    try:
        import playwright.sync_api as sync_api

        sync_api.sync_playwright = _block_browser
        patched += 1
    except Exception:
        # HTTP-only native lanes do not require Playwright to be installed. Browser
        # shards do install it, but absence here should still fail closed at any
        # worker-module browser helper patched above.
        pass

    base.browser_context = _block_browser
    v2.optimized_browser_context = _block_browser
    os.environ["DCE_HTTP_PROBE_GUARD_ACTIVE"] = "1"
    return patched


if __name__ == "__main__":
    install_http_probe_guard()
    v2.main()
