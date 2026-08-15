from __future__ import annotations

import json
import os
from pathlib import Path

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v7 as v7
import dce_worker_v8 as v8  # registers all previous adapters and remains browser fallback

SAM_RESOURCES_URL = "https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources"
SAM_DOWNLOAD_URL = "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{resource_id}/download?api_key=null&token="


def _collect_resource_records(obj, out: list[dict], path: str = "root") -> None:
    if isinstance(obj, dict):
        low = {str(k).casefold(): v for k, v in obj.items()}
        rid = next((low.get(k) for k in ("resourceid", "resource_id") if low.get(k) not in (None, "")), None)
        if rid is not None:
            access = next((low.get(k) for k in ("access", "packageaccesslevel", "explicitaccess") if k in low), None)
            name = next((low.get(k) for k in ("resourcename", "filename", "file_name", "name") if low.get(k)), None)
            deleted = next((low.get(k) for k in ("deleted", "isdeleted", "is_deleted") if k in low), None)
            out.append({
                "resource_id": str(rid).strip(),
                "name": str(name or "")[:500],
                "access": access,
                "deleted": deleted,
                "path": path,
            })
        for k, v in obj.items():
            _collect_resource_records(v, out, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5000]):
            _collect_resource_records(v, out, f"{path}[{i}]")


def _is_deleted(value) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "deleted"}


def _is_public_access(value) -> bool:
    # Live SAM v3 canary observed access=0 for public attachments and access=1 for
    # controlled files. Missing access is allowed through as "unspecified" because
    # the public download endpoint itself remains the authority and direct_download
    # validates that an actual file was returned.
    if value is None or str(value).strip() == "":
        return True
    return str(value).strip().casefold() in {"0", "public", "false", "none", "unrestricted"}


def _sam_http_resources(candidate: dict, out: Path, manifest: dict) -> tuple[list[dict], str]:
    notice_id = v7._sam_notice_id(candidate)
    if not notice_id:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "SAM_PUBLIC_RESOURCES_HTTP_V9", "outcome": "NO_NOTICE_ID"
        })
        return [], "NO_NOTICE_ID"

    url = SAM_RESOURCES_URL.format(notice_id=notice_id)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/9.0 public procurement research",
        "Accept": "application/json, text/plain, */*",
        "Referer": v7._sam_public_url(candidate),
    })
    try:
        r = session.get(
            url,
            params={"api_key": "null", "excludeDeleted": "false", "withScanResult": "false"},
            timeout=35,
        )
        attempt = {
            "method": "SAM_PUBLIC_RESOURCES_HTTP_V9",
            "url": r.url,
            "http_status": r.status_code,
            "content_type": str(r.headers.get("content-type") or "")[:200],
            "bytes": len(r.content),
        }
        manifest.setdefault("dce_method_attempts", []).append(attempt)
        if not r.ok:
            attempt["outcome"] = "HTTP_ERROR"
            return [], "HTTP_ERROR"
        try:
            data = r.json()
        except Exception:
            attempt["outcome"] = "NON_JSON"
            return [], "NON_JSON"

        records: list[dict] = []
        _collect_resource_records(data, records)
        dedup: dict[str, dict] = {}
        for rec in records:
            rid = str(rec.get("resource_id") or "").strip()
            if rid and rid not in dedup:
                dedup[rid] = rec
        records = list(dedup.values())
        public_records = [r for r in records if not _is_deleted(r.get("deleted")) and _is_public_access(r.get("access"))]
        restricted = [r for r in records if not _is_deleted(r.get("deleted")) and not _is_public_access(r.get("access"))]
        attempt.update({
            "outcome": "RESOURCES_FOUND" if records else "NO_RESOURCES",
            "resources_total": len(records),
            "public_or_unspecified": len(public_records),
            "restricted": len(restricted),
            "public_resources": public_records[:100],
            "restricted_resources": restricted[:50],
        })
        (out / "sam_http_resources.json").write_text(
            json.dumps({"notice_id": notice_id, "resources": records}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return public_records, "RESOURCES_FOUND" if records else "NO_RESOURCES"
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "SAM_PUBLIC_RESOURCES_HTTP_V9", "url": url,
            "outcome": "ERROR", "error": repr(exc)[:700],
        })
        return [], "ERROR"


def _download_sam_public_resources(candidate: dict, out: Path, manifest: dict, records: list[dict]) -> int:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/9.0 public procurement research",
        "Accept": "*/*",
        "Referer": v7._sam_public_url(candidate),
    })
    downloaded = 0
    for rec_meta in records[:120]:
        rid = str(rec_meta.get("resource_id") or "").strip()
        if not rid:
            continue
        url = SAM_DOWNLOAD_URL.format(resource_id=rid)
        rec = base.direct_download(url, out, session)
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "SAM_PUBLIC_RESOURCE_DOWNLOAD_V9",
            "resource_id": rid,
            "resource_name": rec_meta.get("name"),
            "access": rec_meta.get("access"),
            "url": url,
            "outcome": "DOWNLOADED" if rec else "NOT_FILE",
        })
        if rec:
            manifest.setdefault("files", []).append(rec)
            downloaded += 1
    return downloaded


def adapter_sam_public_v9(candidate: dict, out: Path, manifest: dict):
    """HTTP-first public SAM resolver; Playwright v8 is fallback only.

    Live canaries established that public opportunity attachment metadata is served
    by SAM's v3 resources endpoint without an external API key. This path avoids
    browser startup entirely for the common case and follows the public download
    redirect immediately to the short-lived signed S3 object.
    """
    manifest.setdefault("dce_method_attempts", [])

    # Preserve discovery-supplied direct public files as the cheapest route.
    if v7.v4._attempt_direct(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    records, state = _sam_http_resources(candidate, out, manifest)
    if records and _download_sam_public_resources(candidate, out, manifest, records):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    if str(os.getenv("SAM_HTTP_ONLY") or "").strip().casefold() in {"1", "true", "yes"}:
        # This mode is used by the no-Playwright production canary. If the resource
        # endpoint proves all attachments controlled, expose that; otherwise keep a
        # retryable/public-file miss rather than fabricating auth from page boilerplate.
        all_attempts = manifest.get("dce_method_attempts") or []
        resource_attempt = next((a for a in reversed(all_attempts) if a.get("method") == "SAM_PUBLIC_RESOURCES_HTTP_V9"), {})
        if int(resource_attempt.get("resources_total") or 0) > 0 and int(resource_attempt.get("public_or_unspecified") or 0) == 0:
            manifest["status"] = "AUTH_REQUIRED"
        elif state in {"HTTP_ERROR", "NON_JSON", "ERROR"}:
            manifest["status"] = "ERROR_RETRYABLE"
        else:
            manifest["status"] = "NO_PUBLIC_FILE"
        return

    # Rare or changed SAM UI/API behavior: retain proven v8 browser fallback.
    return v8.adapter_sam_public_v8(candidate, out, manifest)


base.ADAPTERS["US_SAM"] = adapter_sam_public_v9
base.ADAPTERS["US_SAM_BULK"] = adapter_sam_public_v9

if __name__ == "__main__":
    v2.main()
