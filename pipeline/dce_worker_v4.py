from __future__ import annotations

from pathlib import Path

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v3 as v3


def generic_public_page_adapter(candidate: dict, out: Path, manifest: dict):
    """Conservative long-tail TED downstream first pass.

    Reuse the validated v3 public-page extractor, but never interpret failure to
    find a visible/direct document link as proof that the portal has no public
    DCE. Route-specific JS/API/form adapters may still be needed, so preserve an
    explicit unresolved status for future prioritisation.
    """
    v3._public_page_adapter(candidate, out, manifest)
    if manifest.get("status") == "NO_PUBLIC_FILE":
        manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"


base.ADAPTERS["GENERIC_PUBLIC_PAGE"] = generic_public_page_adapter


if __name__ == "__main__":
    v2.main()
