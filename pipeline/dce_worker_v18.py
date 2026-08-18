from __future__ import annotations

from pathlib import Path

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v12 as v12
import dce_worker_v17 as v17  # register the complete validated v17 stack first

# Capture the fully validated current handlers after v17 has registered the whole
# resolver chain. V18 changes only ordering for Hungary EKR: the existing explicit
# selected-document helper already runs today, but only *after* the expensive broad
# SPA cascade. Trying that exact helper first avoids spending the whole worker budget
# on generic HTTP/browser discovery before reaching the portal-specific control.
_OLD_HU_PUBLIC = base.ADAPTERS.get("HU_EKR_PUBLIC")
_OLD_HU = base.ADAPTERS.get("HU_EKR")


def adapter_hu_ekr_v18(candidate: dict, out: Path, manifest: dict) -> None:
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])

    route = candidate.get("route") or {}
    detail = str(route.get("detail_url") or candidate.get("notice_url") or "")
    applicable = "ekr.gov.hu" in detail.casefold()

    if applicable:
        manifest["hu_ekr_v18_fast_first"] = True
        if v12._ekr_selected_document_download(candidate, out, manifest):
            manifest["status"] = "DOWNLOADED_PUBLIC"
            return

    # Fail open to the exact previous validated resolver. This preserves all legacy
    # browser/network discovery and access-gate semantics when the targeted EKR path
    # is absent, changed, or temporarily unsuccessful.
    fallback = _OLD_HU_PUBLIC or _OLD_HU
    if fallback:
        return fallback(candidate, out, manifest)
    manifest["status"] = "ROUTE_INCOMPLETE"


base.ADAPTERS["HU_EKR_PUBLIC"] = adapter_hu_ekr_v18
base.ADAPTERS["HU_EKR"] = adapter_hu_ekr_v18

if __name__ == "__main__":
    v2.main()
