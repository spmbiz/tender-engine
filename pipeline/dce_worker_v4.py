from __future__ import annotations

from pathlib import Path

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v3 as v3


def generic_public_page_adapter(candidate: dict, out: Path, manifest: dict):
    """Conservative public-page DCE first pass for long-tail portals.

    Reuse the validated v3 public-page extractor, but never interpret failure to
    find a visible/direct document link as proof that the portal has no public
    DCE. Route-specific JS/API/form adapters may still be needed, so preserve an
    explicit unresolved status for future prioritisation.
    """
    v3._public_page_adapter(candidate, out, manifest)
    if manifest.get("status") == "NO_PUBLIC_FILE":
        manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"


# These discovery sources expose public notice/detail URLs. Start with the same
# conservative HTTP + browser link discovery used for TED long-tail downstream
# portals. This does not bypass login, CAPTCHA, MFA, or controlled attachments.
for portal in (
    "GENERIC_PUBLIC_PAGE",
    "CA_CANADABUYS",
    "QC_SEAO",
    "DE_DOE",
    "FR_BOAMP",
    "NZ_GETS",
    "AU_AUSTENDER",
):
    base.ADAPTERS[portal] = generic_public_page_adapter


if __name__ == "__main__":
    v2.main()
