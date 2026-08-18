from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v15 as v15
import dce_worker_v16 as v16  # registers the complete v16 resolver stack first
import placsp_atom

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None

PLACSP_CACHE_TTL = max(30, min(3600, int(os.getenv("ES_DCE_ATOM_CACHE_TTL", "600"))))


def _cache_root() -> Path:
    root = Path(os.getenv("DCE_SHARED_CACHE_DIR", ".cache/dce")) / "placsp-atom"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_paths(url: str) -> tuple[Path, Path, Path]:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    root = _cache_root()
    return root / f"{key}.atom", root / f"{key}.json", root / f"{key}.lock"


def _read_cache(url: str) -> tuple[bytes, str] | None:
    payload_path, meta_path, _ = _cache_paths(url)
    try:
        age = time.time() - payload_path.stat().st_mtime
        if age < 0 or age > PLACSP_CACHE_TTL:
            return None
        body = payload_path.read_bytes()
        if not body:
            return None
        ET.fromstring(body)
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return body, str(meta.get("resolved_url") or url)
    except Exception:
        return None


def _write_cache(url: str, body: bytes, resolved_url: str) -> None:
    payload_path, meta_path, _ = _cache_paths(url)
    ET.fromstring(body)
    stamp = f"{os.getpid()}-{time.time_ns()}"
    payload_tmp = payload_path.with_name(payload_path.name + f".{stamp}.tmp")
    meta_tmp = meta_path.with_name(meta_path.name + f".{stamp}.tmp")
    payload_tmp.write_bytes(body)
    meta_tmp.write_text(json.dumps({"source_url": url, "resolved_url": resolved_url, "cached_at": time.time()}), encoding="utf-8")
    os.replace(payload_tmp, payload_path)
    os.replace(meta_tmp, meta_path)


@contextlib.contextmanager
def _url_lock(url: str):
    _, _, lock_path = _cache_paths(url)
    handle = lock_path.open("a+b")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        handle.close()


def _fetch_atom_cached(session: requests.Session, url: str, read_timeout: int) -> tuple[bytes, str, int, bool]:
    cached = _read_cache(url)
    if cached:
        return cached[0], cached[1], 200, True
    with _url_lock(url):
        cached = _read_cache(url)
        if cached:
            return cached[0], cached[1], 200, True
        response = session.get(url, timeout=(5, read_timeout), allow_redirects=True)
        body = response.content
        if response.ok and body:
            try:
                _write_cache(url, body, response.url)
            except Exception:
                pass
        return body, response.url, response.status_code, False


def _resolve_from_atom_cached(candidate: dict, manifest: dict) -> tuple[list[str], bool, str]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/17.0 public procurement research", "Accept": "application/atom+xml,application/xml,text/xml,*/*"})
    started = time.monotonic()
    seen: set[str] = set()
    telemetry: list[dict] = []
    for lane, start_url in v15._feed_order(candidate):
        url = start_url
        page_no = 0
        while url and url not in seen and page_no < v15.PLACSP_ATOM_MAX_PAGES and time.monotonic() - started < v15.PLACSP_ATOM_BUDGET:
            seen.add(url)
            page_no += 1
            remaining = max(1.0, v15.PLACSP_ATOM_BUDGET - (time.monotonic() - started))
            read_timeout = max(3, min(v15.PLACSP_ATOM_TIMEOUT, int(remaining)))
            try:
                body, resolved_url, status, cache_hit = _fetch_atom_cached(session, url, read_timeout)
                row = {"lane": lane, "page": page_no, "url": url, "resolved_url": resolved_url, "http_status": status, "bytes": len(body), "cache_hit": cache_hit}
                telemetry.append(row)
                if status < 200 or status >= 300:
                    row["outcome"] = "HTTP_ERROR"
                    break
                root = ET.fromstring(body)
            except Exception as exc:
                telemetry.append({"lane": lane, "page": page_no, "url": url, "outcome": "ERROR", "error": repr(exc)[:600]})
                break
            for entry in placsp_atom.entries(root):
                matched, match_method = v15._entry_match(entry, candidate)
                if not matched:
                    continue
                urls = placsp_atom.document_urls(entry, resolved_url)
                manifest["placsp_atom_resolution"] = {"lane": lane, "page": page_no, "feed_url": resolved_url, "match_method": match_method, "candidate_id": placsp_atom.candidate_id(entry), "contract_folder_id": placsp_atom.contract_folder_id(entry), "document_urls": urls, "elapsed_seconds": round(time.monotonic() - started, 3), "cache_hit": cache_hit}
                manifest.setdefault("dce_method_attempts", []).append({"method": "ES_PLACSP_OFFICIAL_ATOM_V17", "outcome": "ENTRY_FOUND", **manifest["placsp_atom_resolution"], "telemetry": telemetry})
                return urls, True, lane
            url = placsp_atom.next_link(root, resolved_url)
    manifest.setdefault("dce_method_attempts", []).append({"method": "ES_PLACSP_OFFICIAL_ATOM_V17", "outcome": "ENTRY_NOT_FOUND", "elapsed_seconds": round(time.monotonic() - started, 3), "telemetry": telemetry})
    return [], False, ""


def adapter_placsp_v17(candidate: dict, out: Path, manifest: dict) -> None:
    before = len(manifest.get("dce_method_attempts") or [])
    v15.adapter_placsp_v15(candidate, out, manifest)
    if manifest.get("files"):
        return
    resolution = manifest.get("placsp_atom_resolution") or {}
    if not (resolution.get("document_urls") or []):
        return
    attempts = (manifest.get("dce_method_attempts") or [])[before:]
    document_attempts = [a for a in attempts if isinstance(a, dict) and str(a.get("method") or "").startswith("ES_PLACSP_") and "DOCUMENT" in str(a.get("method") or "")]
    retryable = any(str(a.get("outcome") or "") == "ERROR" or int(a.get("http_status") or 0) == 429 or int(a.get("http_status") or 0) >= 500 for a in document_attempts)
    if retryable:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["placsp_retry_reason"] = "OFFICIAL_DOCUMENT_ENDPOINT_TEMPORARY_FAILURE"


v15._resolve_from_atom = _resolve_from_atom_cached
base.ADAPTERS["ES_PLACSP"] = adapter_placsp_v17

if __name__ == "__main__":
    v2.main()
