from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import dce_worker_v18 as v18


def main() -> None:
    candidate = {
        "portal": "HU_EKR_PUBLIC",
        "notice_url": "https://ekr.gov.hu/portal/kozbeszerzes/eljarasok/EKR000199982025/reszletek",
        "route": {"detail_url": "https://ekr.gov.hu/portal/kozbeszerzes/eljarasok/EKR000199982025/reszletek"},
    }

    old_fast = v18.v12._ekr_selected_document_download
    old_public = v18._OLD_HU_PUBLIC
    old_hu = v18._OLD_HU
    try:
        events: list[str] = []

        def fast_miss(candidate, out, manifest):
            events.append("fast")
            return False

        def fallback(candidate, out, manifest):
            events.append("fallback")
            manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"

        v18.v12._ekr_selected_document_download = fast_miss
        v18._OLD_HU_PUBLIC = fallback
        v18._OLD_HU = None
        with TemporaryDirectory() as td:
            manifest = {"files": []}
            v18.adapter_hu_ekr_v18(candidate, Path(td), manifest)
        assert events == ["fast", "fallback"], events
        assert manifest["status"] == "GENERIC_PUBLIC_PAGE_UNRESOLVED"
        assert manifest["hu_ekr_v18_fast_first"] is True

        events.clear()

        def fast_hit(candidate, out, manifest):
            events.append("fast")
            manifest["files"].append({"name": "ekr.zip"})
            return True

        def forbidden_fallback(candidate, out, manifest):
            raise AssertionError("fallback must not run after fast success")

        v18.v12._ekr_selected_document_download = fast_hit
        v18._OLD_HU_PUBLIC = forbidden_fallback
        with TemporaryDirectory() as td:
            manifest = {"files": []}
            v18.adapter_hu_ekr_v18(candidate, Path(td), manifest)
        assert events == ["fast"], events
        assert manifest["status"] == "DOWNLOADED_PUBLIC"
        assert len(manifest["files"]) == 1
        print({"hu_ekr_fast_first": True, "fallback_preserved": True, "status": "ok"})
    finally:
        v18.v12._ekr_selected_document_download = old_fast
        v18._OLD_HU_PUBLIC = old_public
        v18._OLD_HU = old_hu


if __name__ == "__main__":
    main()
