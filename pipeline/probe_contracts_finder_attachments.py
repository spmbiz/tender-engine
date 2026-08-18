from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import requests


BASE = "https://www.contractsfinder.service.gov.uk"
UA = "Tender-Engine/23-probe (+public procurement research)"
ATTACH_RE = re.compile(r"/Notice/(?P<dtype>Attachment|SupplierAttachment)/(?P<id>[0-9a-f-]{36})", re.I)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def magic(body: bytes) -> str:
    if body.startswith(b"PK\x03\x04"):
        return "ZIP_OOXML"
    if body.startswith(b"%PDF-"):
        return "PDF"
    if body.startswith((b"\xd0\xcf\x11\xe0",)):
        return "OLE"
    if body.startswith(b"{\rtf"):
        return "RTF"
    if body.startswith(b"\x1f\x8b"):
        return "GZIP"
    head = body[:300].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "HTML"
    if head.startswith((b"{", b"[")):
        return "JSONISH"
    return "UNKNOWN"


def response_summary(r: requests.Response, body: bytes) -> dict:
    return {
        "status": r.status_code,
        "requested_url": str(r.request.url),
        "final_url": r.url,
        "content_type": r.headers.get("content-type"),
        "content_disposition": r.headers.get("content-disposition"),
        "content_length_header": r.headers.get("content-length"),
        "bytes": len(body),
        "sha256": sha256(body) if body else None,
        "magic": magic(body),
        "history": [{"status": h.status_code, "url": h.url, "location": h.headers.get("location")} for h in r.history],
        "text_preview": body[:1000].decode("utf-8", errors="replace") if magic(body) in {"HTML", "JSONISH", "UNKNOWN"} else None,
    }


def probe_http(session: requests.Session, url: str) -> dict:
    result = {"url": url}
    m = ATTACH_RE.search(url)
    if not m:
        result["error"] = "NOT_ATTACHMENT_URL"
        return result
    aid = m.group("id")
    dtype = m.group("dtype")
    result.update({"id": aid, "data_type_from_url": dtype})

    # Metadata is explicitly documented as a public Published endpoint. It gives
    # filename, MIME type, data type and notice id even when fileContent is null.
    metadata_url = f"{BASE}/Published/AdditionalDetails/{aid}"
    try:
        r = session.get(metadata_url, headers={"Accept": "application/json"}, timeout=20, allow_redirects=True)
        body = r.content[:2_000_000]
        result["metadata_http"] = response_summary(r, body)
        if r.ok:
            try:
                meta = r.json()
            except Exception:
                meta = None
            if isinstance(meta, dict):
                result["metadata"] = {
                    "id": meta.get("id") or meta.get("Id"),
                    "notice_id": meta.get("noticeId") or meta.get("NoticeId"),
                    "data_type": meta.get("dataType") or meta.get("DataType"),
                    "document_type": meta.get("documentType") or meta.get("DocumentType"),
                    "filename": meta.get("filename") or meta.get("Filename"),
                    "mime_type": meta.get("mimeType") or meta.get("MimeType"),
                    "link": meta.get("link") or meta.get("Link"),
                    "file_content_present": bool(meta.get("fileContent") or meta.get("FileContent")),
                }
    except Exception as exc:
        result["metadata_error"] = repr(exc)

    # The public documentation says Attachment URLs are composed exactly this way.
    # Record the real response instead of assuming it is a file from the URL shape.
    try:
        r = session.get(url, timeout=30, allow_redirects=True)
        body = r.content
        result["attachment_http"] = response_summary(r, body[:5_000_000])
        result["attachment_total_bytes"] = len(body)
    except Exception as exc:
        result["attachment_error"] = repr(exc)
    return result


def probe_browser(urls: list[str]) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return [{"error": f"PLAYWRIGHT_IMPORT:{exc!r}"}]
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=None)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        for url in urls:
            rec = {"url": url, "download": False}
            try:
                page.set_content(f'<a id="probe" href="{url}">download</a>')
                with page.expect_download(timeout=15000) as info:
                    page.locator("#probe").click()
                dl = info.value
                failure = dl.failure()
                rec.update({"download": not bool(failure), "suggested_filename": dl.suggested_filename, "failure": failure})
                if not failure:
                    path = dl.path()
                    if path:
                        p = Path(path)
                        body = p.read_bytes()[:5_000_000]
                        rec.update({"bytes": p.stat().st_size, "magic": magic(body), "sha256_prefix_body": sha256(body)})
            except Exception as exc:
                rec["error"] = repr(exc)
            out.append(rec)
        browser.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--out", type=Path, default=Path("contracts-finder-probe.json"))
    ap.add_argument("--browser", action="store_true")
    args = ap.parse_args()
    if not args.url:
        raise SystemExit("at least one --url is required")
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    report = {"http": [probe_http(s, u) for u in args.url]}
    if args.browser:
        report["browser"] = probe_browser(args.url)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
