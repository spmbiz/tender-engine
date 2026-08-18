from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v5 as v5
import dce_worker_v17 as v17  # register the complete validated v17 stack first

GR_FAST_CONNECT_TIMEOUT = max(2, min(10, int(os.getenv("GR_DCE_FAST_CONNECT_TIMEOUT", "4"))))
GR_FAST_READ_TIMEOUT = max(5, min(30, int(os.getenv("GR_DCE_FAST_READ_TIMEOUT", "12"))))


def _canonical_gr_url(candidate: dict) -> str | None:
    notice_id = str(candidate.get("notice_id") or "").strip()
    if not notice_id:
        cid = str(candidate.get("candidate_id") or "")
        if cid.upper().startswith("GR-KHMDHS:"):
            notice_id = cid.split(":", 1)[1].strip()
    if not notice_id:
        return None
    return f"https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/{notice_id}"


def _fast_canonical_fetch(url: str, candidate: dict, out: Path, manifest: dict) -> bool:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/18.0 public procurement research",
        "Accept": "application/pdf,application/zip,application/octet-stream,*/*",
    })
    try:
        r = session.get(url, timeout=(GR_FAST_CONNECT_TIMEOUT, GR_FAST_READ_TIMEOUT), allow_redirects=True)
        ct = (r.headers.get("content-type") or "").lower()
        cd = (r.headers.get("content-disposition") or "").lower()
        prefix = bytes(r.content[:8]) if r.content else b""
        fileish = bool(
            r.ok and r.content and (
                "attachment" in cd
                or "application/pdf" in ct
                or "application/zip" in ct
                or "application/octet-stream" in ct
                or prefix.startswith(b"%PDF-")
                or prefix.startswith(b"PK\x03\x04")
            )
        )
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "GR_KHMDHS_CANONICAL_FAST_V18",
            "url": url,
            "resolved_url": r.url,
            "http_status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "bytes": len(r.content),
            "magic": prefix.hex(),
            "outcome": "FILE_CONFIRMED" if fileish else "NOT_FILE",
        })
        if not fileish:
            return False
        manifest.setdefault("files", []).append(base.persist_bytes(
            out,
            v5._gr_filename(r, candidate),
            r.content,
            r.url,
            r.headers.get("content-type"),
        ))
        return True
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "GR_KHMDHS_CANONICAL_FAST_V18",
            "url": url,
            "outcome": "FAST_PROBE_FAILED_FALLBACK_REQUIRED",
            "error": repr(exc)[:600],
        })
        return False


def adapter_greece_v18(candidate: dict, out: Path, manifest: dict) -> None:
    """Low-latency first-party probe; preserve v17/v5 recall via full fallback.

    The official KHMDHS attachment endpoint is deterministic from notice_id. Some
    historical route.document_urls are stale/slow, so probing the canonical endpoint
    first avoids waiting on them. Failure never rejects: the validated robust adapter
    runs unchanged afterwards.
    """
    manifest.setdefault("dce_method_attempts", [])
    canonical = _canonical_gr_url(candidate)
    if canonical and _fast_canonical_fetch(canonical, candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        manifest["gr_v18_fast_path"] = True
        return
    v5.adapter_greece_robust(candidate, out, manifest)


base.ADAPTERS["GR_KHMDHS"] = adapter_greece_v18

if __name__ == "__main__":
    v2.main()
