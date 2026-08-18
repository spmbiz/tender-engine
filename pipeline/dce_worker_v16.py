from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v4 as v4
import dce_worker_v15 as v15  # registers the complete v15 resolver stack first
from ocds_release_normalizer import docs_from_release

ZA_RELEASE_API = "https://ocds-api.etenders.gov.za/api/OCDSReleases/release/{ocid}"
ZA_API_TIMEOUT = max(8, min(60, int(os.getenv("ZA_DCE_API_TIMEOUT", "25"))))
ZA_DOC_LIMIT = max(1, min(200, int(os.getenv("ZA_DCE_DOC_LIMIT", "80"))))


def _za_ocid(candidate: dict) -> str:
    route = candidate.get("route") or {}
    for value in (
        candidate.get("ocid"),
        candidate.get("procedure_id"),
        route.get("ocid") if isinstance(route, dict) else None,
        route.get("procedure_id") if isinstance(route, dict) else None,
    ):
        value = str(value or "").strip()
        if value.startswith("ocds-"):
            return value

    cid = str(candidate.get("candidate_id") or "")
    match = re.search(r"(?:^|:)(ocds-[A-Za-z0-9-]+?)(?:-\d{4}-\d{2}-\d{2})?$", cid)
    return match.group(1) if match else ""


def _direct_candidate_docs(candidate: dict, out: Path, manifest: dict) -> bool:
    return v4._attempt_direct(candidate, out, manifest)


def _api_release(candidate: dict, manifest: dict) -> tuple[dict | None, str]:
    ocid = _za_ocid(candidate)
    if not ocid:
        manifest.setdefault("dce_method_attempts", []).append(
            {"method": "ZA_OCDS_RELEASE_API_V16", "outcome": "NO_OCID"}
        )
        return None, "NO_OCID"

    url = ZA_RELEASE_API.format(ocid=quote(ocid, safe="-"))
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Tender-Engine/16.0 public procurement research",
            "Accept": "application/json",
        }
    )
    try:
        r = session.get(url, timeout=(5, ZA_API_TIMEOUT), allow_redirects=True)
        attempt = {
            "method": "ZA_OCDS_RELEASE_API_V16",
            "url": url,
            "resolved_url": r.url,
            "http_status": r.status_code,
            "content_type": str(r.headers.get("content-type") or "")[:160],
            "bytes": len(r.content),
        }
        manifest.setdefault("dce_method_attempts", []).append(attempt)
        if r.status_code == 404:
            attempt["outcome"] = "RELEASE_NOT_FOUND"
            return None, "NOT_FOUND"
        if r.status_code == 429 or r.status_code >= 500:
            attempt["outcome"] = "RETRYABLE_HTTP"
            return None, "RETRYABLE"
        if not r.ok:
            attempt["outcome"] = "HTTP_ERROR"
            return None, "HTTP_ERROR"
        data = r.json()
        if not isinstance(data, dict):
            attempt["outcome"] = "NON_OBJECT_JSON"
            return None, "BAD_PAYLOAD"
        attempt["outcome"] = "RELEASE_FOUND"
        return data, "OK"
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append(
            {
                "method": "ZA_OCDS_RELEASE_API_V16",
                "url": url,
                "outcome": "ERROR",
                "error": repr(exc)[:700],
            }
        )
        return None, "RETRYABLE"


def _download_release_docs(release: dict, out: Path, manifest: dict) -> tuple[int, int]:
    docs = docs_from_release(release)
    manifest["za_ocds_document_descriptors"] = docs[:ZA_DOC_LIMIT]
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Tender-Engine/16.0 public procurement research",
            "Accept": "application/pdf,application/zip,application/octet-stream,*/*",
        }
    )
    downloaded = 0
    attempted = 0
    seen: set[str] = set()
    for doc in docs[:ZA_DOC_LIMIT]:
        url = str(doc.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        attempted += 1
        rec = base.direct_download(url, out, session)
        manifest.setdefault("dce_method_attempts", []).append(
            {
                "method": "ZA_OCDS_DOCUMENT_V16",
                "url": url,
                "document_id": doc.get("id"),
                "document_type": doc.get("document_type"),
                "title": doc.get("title"),
                "format": doc.get("format"),
                "outcome": "DOWNLOADED" if rec else "NOT_FILE",
            }
        )
        if rec:
            manifest.setdefault("files", []).append(rec)
            downloaded += 1
    return downloaded, attempted


def adapter_za_etenders_v16(candidate: dict, out: Path, manifest: dict) -> None:
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])

    if _direct_candidate_docs(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    release, state = _api_release(candidate, manifest)
    if release is None:
        manifest["status"] = (
            "ERROR_RETRYABLE"
            if state in {"RETRYABLE", "BAD_PAYLOAD"}
            else ("NO_PUBLIC_FILE" if state == "NOT_FOUND" else "ROUTE_INCOMPLETE")
        )
        return

    try:
        (out.parent / "za_ocds_release.json").write_text(
            json.dumps(release, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    downloaded, attempted = _download_release_docs(release, out, manifest)
    if downloaded:
        manifest["status"] = "DOWNLOADED_PUBLIC"
    elif attempted:
        manifest["status"] = "ERROR_RETRYABLE"
    else:
        manifest["status"] = "NO_PUBLIC_FILE"


for portal in ("ZA_ETENDERS", "ZA_ETENDERS_OCDS"):
    base.ADAPTERS[portal] = adapter_za_etenders_v16

if __name__ == "__main__":
    v2.main()
