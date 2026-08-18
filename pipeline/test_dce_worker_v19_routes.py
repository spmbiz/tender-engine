from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import dce_worker_v19 as v19


def main() -> None:
    detail_only = {
        "portal": "HU_EKR_PUBLIC",
        "notice_url": "https://ekr.gov.hu/portal/kozbeszerzes/eljarasok/EKR000199982025/reszletek",
        "route": {"detail_url": "https://ekr.gov.hu/portal/kozbeszerzes/eljarasok/EKR000199982025/reszletek"},
    }
    explicit = {
        **detail_only,
        "route": {
            "detail_url": detail_only["notice_url"],
            "document_urls": ["https://ekr.gov.hu/public/example.zip"],
        },
    }
    assert v19._detail_url(detail_only).startswith("https://ekr.gov.hu/")
    assert v19._explicit_document_routes(detail_only) == []
    assert len(v19._explicit_document_routes(explicit)) == 1

    controls = [
        {"index": 0, "text": "EKR PDF letöltés", "aria": "", "title": "", "visible": True, "disabled": False},
        {"index": 1, "text": "5_rész.zip", "aria": "", "title": "", "visible": True, "disabled": False},
        {"index": 2, "text": "Szerződés.docx", "aria": "", "title": "", "visible": True, "disabled": False},
        {"index": 3, "text": "Bejelentkezés", "aria": "", "title": "", "visible": True, "disabled": False},
        {"index": 4, "text": "Áttekintés", "aria": "", "title": "", "visible": True, "disabled": False},
        {"index": 5, "text": "KD_Bérházfelújítás_2025 .docx", "aria": "", "title": "", "visible": True, "disabled": False},
    ]
    assert v19._safe_ekr_control_indices(controls) == [5, 2, 1, 0]
    assert v19.EKR_API_DOWNLOAD_RE.search(
        "https://ekr.gov.hu/api/publikus/kozbeszerzesi-hirdetmenyek/123/dokumentum-letoltes"
    )

    old_http = v19._bounded_http_probe
    old_browser = v19._bounded_browser_download
    old_public = v19._OLD_HU_PUBLIC
    old_hu = v19._OLD_HU
    try:
        events: list[str] = []

        def no_http(detail, out, manifest):
            events.append("http")
            return False

        def no_browser(detail, out, manifest):
            events.append("browser")
            return False

        def fallback(candidate, out, manifest):
            events.append("fallback")
            manifest["status"] = "DOWNLOADED_PUBLIC"
            manifest.setdefault("files", []).append({"name": "legacy.zip"})

        v19._bounded_http_probe = no_http
        v19._bounded_browser_download = no_browser
        v19._OLD_HU_PUBLIC = fallback
        v19._OLD_HU = None

        with TemporaryDirectory() as td:
            manifest = {"files": []}
            v19.adapter_hu_ekr_v19(detail_only, Path(td), manifest)
        assert events == ["http", "browser"], events
        assert manifest["status"] == "ERROR_RETRYABLE", manifest
        assert manifest["error"] == "HU_EKR_DETAIL_ONLY_TARGETED_V19_EXHAUSTED"

        events.clear()
        with TemporaryDirectory() as td:
            manifest = {"files": []}
            v19.adapter_hu_ekr_v19(explicit, Path(td), manifest)
        assert events == ["fallback"], events
        assert manifest["status"] == "DOWNLOADED_PUBLIC"
        assert len(manifest["files"]) == 1

        events.clear()

        def hit_http(detail, out, manifest):
            events.append("http")
            manifest.setdefault("files", []).append({"name": "bounded.zip"})
            return True

        v19._bounded_http_probe = hit_http
        with TemporaryDirectory() as td:
            manifest = {"files": []}
            v19.adapter_hu_ekr_v19(detail_only, Path(td), manifest)
        assert events == ["http"], events
        assert manifest["status"] == "DOWNLOADED_PUBLIC"
        print({"hu_ekr_detail_only": "targeted_network", "explicit_routes": "legacy_preserved", "safe_controls": 4, "procurement_doc_first": True, "status": "ok"})
    finally:
        v19._bounded_http_probe = old_http
        v19._bounded_browser_download = old_browser
        v19._OLD_HU_PUBLIC = old_public
        v19._OLD_HU = old_hu


if __name__ == "__main__":
    main()
