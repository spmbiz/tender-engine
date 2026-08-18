from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

import dce_worker as base
import dce_worker_v19 as v19  # register complete validated V19 stack first

_OLD_IE = base.ADAPTERS.get("IRELAND_ETENDERS")
_RESOURCE_RE = re.compile(r"(?:resourceId=|(?:^|[^0-9]))([0-9]{5,})(?:[^0-9]|$)", re.I)


def _resource_id(candidate: dict) -> str:
    route = candidate.get("route") or {}
    values = []
    if isinstance(route, dict):
        values.extend([
            route.get("resource_id"),
            route.get("resourceId"),
            route.get("detail_url"),
            route.get("documents_url"),
        ])
    values.extend([
        candidate.get("resource_id"),
        candidate.get("portal_ref"),
        candidate.get("notice_url"),
        candidate.get("candidate_id"),
    ])
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text.isdigit() and len(text) >= 5:
            return text
        match = re.search(r"resourceId=([0-9]{5,})", text, re.I)
        if match:
            return match.group(1)
        # Candidate IDs commonly carry `IE:<resource_id>`.
        match = re.search(r"(?:^|:)IE:?([0-9]{5,})(?:$|[^0-9])", text, re.I)
        if match:
            return match.group(1)
    return ""


def _safe_zip(body: bytes) -> bool:
    if not body or len(body) <= 1000 or body[:4] != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = archive.namelist()
            return bool(names) and archive.testzip() is None
    except Exception:
        return False


def _anonymous_zip_http(candidate: dict, out: Path, manifest: dict) -> bool:
    resource = _resource_id(candidate)
    if not resource:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "IE_ETENDERS_ANON_ZIP_HTTP_V20",
            "outcome": "SKIP_NO_RESOURCE_ID",
        })
        return False

    url = f"https://www.etenders.gov.ie/epps/cft/prepareAnonymousDownload.do?resourceId={resource}&isContract=null"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/20 public procurement research",
        "Accept": "application/zip,application/octet-stream,*/*",
    })
    try:
        response = session.get(url, timeout=(4, 10), allow_redirects=True)
        body = response.content or b""
        safe = bool(response.ok and _safe_zip(body))
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "IE_ETENDERS_ANON_ZIP_HTTP_V20",
            "url": url,
            "resolved_url": response.url,
            "http_status": response.status_code,
            "bytes": len(body),
            "content_type": response.headers.get("content-type"),
            "safe_zip": safe,
            "outcome": "DOWNLOADED" if safe else "FALLBACK",
        })
        if not safe:
            return False
        record = base.persist_bytes(
            out,
            base.filename_from_response(response, f"etenders-{resource}.zip"),
            body,
            response.url,
            response.headers.get("content-type"),
        )
        manifest.setdefault("files", []).append(record)
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return True
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "IE_ETENDERS_ANON_ZIP_HTTP_V20",
            "url": url,
            "outcome": "ERROR_FALLBACK",
            "error": repr(exc)[:600],
        })
        return False


def adapter_ireland_v20(candidate: dict, out: Path, manifest: dict):
    # Exact official anonymous ZIP endpoint first. Any ambiguity, protected flow,
    # malformed payload, HTTP error, or timeout falls through to the previously
    # validated browser-capable resolver unchanged.
    if _anonymous_zip_http(candidate, out, manifest):
        return
    if _OLD_IE is None:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return
    return _OLD_IE(candidate, out, manifest)


base.ADAPTERS["IRELAND_ETENDERS"] = adapter_ireland_v20

if __name__ == "__main__":
    base.main()
