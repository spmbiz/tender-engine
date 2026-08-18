from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import dce_worker as base
import dce_worker_v20 as v20


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ITT.pdf", b"%PDF-1.4\n" + b"x" * 1500)
    return buf.getvalue()


class _Response:
    def __init__(self, body: bytes, status: int = 200, url: str = "https://www.etenders.gov.ie/epps/cft/prepareAnonymousDownload.do?resourceId=8825829&isContract=null"):
        self.content = body
        self.status_code = status
        self.url = url
        self.headers = {"content-type": "application/zip", "content-disposition": 'attachment; filename="documents.zip"'}
        self.ok = 200 <= status < 400


class _Session:
    response = _Response(_zip_bytes())

    def __init__(self):
        self.headers = {}

    def get(self, *args, **kwargs):
        return self.response


def test_resource_id_extraction():
    assert v20._resource_id({"route": {"resource_id": "8825829"}}) == "8825829"
    assert v20._resource_id({"notice_url": "https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId=8803742"}) == "8803742"
    assert v20._resource_id({"candidate_id": "IE:8787124"}) == "8787124"


def test_http_zip_short_circuits_browser(monkeypatch=None):
    original_session = v20.requests.Session
    original_old = v20._OLD_IE
    called = {"fallback": 0}
    try:
        v20.requests.Session = _Session
        def fallback(candidate, out, manifest):
            called["fallback"] += 1
            manifest["status"] = "FALLBACK_CALLED"
        v20._OLD_IE = fallback
        with tempfile.TemporaryDirectory() as td:
            manifest = {"files": [], "dce_method_attempts": []}
            v20.adapter_ireland_v20({"route": {"resource_id": "8825829"}}, Path(td), manifest)
            assert manifest["status"] == "DOWNLOADED_PUBLIC"
            assert len(manifest["files"]) == 1
            assert manifest["files"][0]["name"] == "documents.zip"
            assert called["fallback"] == 0
    finally:
        v20.requests.Session = original_session
        v20._OLD_IE = original_old


def test_non_zip_preserves_exact_fallback():
    original_session = v20.requests.Session
    original_old = v20._OLD_IE
    called = {"fallback": 0}
    class BadSession(_Session):
        response = _Response(b"<html>association/login</html>", 200)
    try:
        v20.requests.Session = BadSession
        def fallback(candidate, out, manifest):
            called["fallback"] += 1
            manifest["status"] = "AUTH_REQUIRED"
        v20._OLD_IE = fallback
        with tempfile.TemporaryDirectory() as td:
            manifest = {"files": [], "dce_method_attempts": []}
            v20.adapter_ireland_v20({"route": {"resource_id": "8825829"}}, Path(td), manifest)
            assert manifest["status"] == "AUTH_REQUIRED"
            assert not manifest["files"]
            assert called["fallback"] == 1
    finally:
        v20.requests.Session = original_session
        v20._OLD_IE = original_old


if __name__ == "__main__":
    test_resource_id_extraction()
    test_http_zip_short_circuits_browser()
    test_non_zip_preserves_exact_fallback()
    print("dce_worker_v20 route tests: ok")
