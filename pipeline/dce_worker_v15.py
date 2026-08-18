from __future__ import annotations

import html
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v3 as v3
import dce_worker_v14 as v14  # registers the complete v14 resolver stack first
import placsp_atom

PLACSP_DOC_TIMEOUT = max(15, min(90, int(os.getenv("ES_DCE_DOCUMENT_TIMEOUT", "45"))))
PLACSP_ATOM_TIMEOUT = max(5, min(45, int(os.getenv("ES_DCE_ATOM_TIMEOUT", "12"))))
PLACSP_ATOM_BUDGET = max(8, min(90, int(os.getenv("ES_DCE_ATOM_BUDGET", "28"))))
PLACSP_ATOM_MAX_PAGES = max(1, min(8, int(os.getenv("ES_DCE_ATOM_MAX_PAGES", "4"))))
PLACSP_HTTP_FALLBACK_TIMEOUT = max(5, min(30, int(os.getenv("ES_DCE_HTTP_FALLBACK_TIMEOUT", "12"))))


def _candidate_urls(candidate: dict) -> list[str]:
    out: list[str] = []
    route = candidate.get("route") or {}
    for value in route.get("document_urls") or [] if isinstance(route, dict) else []:
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in out:
            out.append(value)
    for doc in candidate.get("documents") or []:
        value = doc.get("url") if isinstance(doc, dict) else doc
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in out:
            out.append(value)
    return out


def _download_placsp_url(
    url: str,
    out: Path,
    manifest: dict,
    session: requests.Session,
    method: str,
) -> bool:
    try:
        r = session.get(
            url,
            timeout=(6, PLACSP_DOC_TIMEOUT),
            allow_redirects=True,
            stream=False,
        )
        attempt = {
            "method": method,
            "url": url,
            "resolved_url": r.url,
            "http_status": r.status_code,
            "content_type": str(r.headers.get("content-type") or "")[:200],
            "content_disposition": str(r.headers.get("content-disposition") or "")[:300],
            "bytes": len(r.content),
        }
        manifest.setdefault("dce_method_attempts", []).append(attempt)
        if not (r.ok and r.content and base.looks_like_file(r)):
            attempt["outcome"] = "NOT_FILE"
            return False
        rec = base.persist_bytes(
            out,
            base.filename_from_response(r, "placsp-document.bin"),
            r.content,
            r.url,
            r.headers.get("content-type"),
        )
        manifest.setdefault("files", []).append(rec)
        attempt["outcome"] = "DOWNLOADED"
        return True
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append(
            {
                "method": method,
                "url": url,
                "outcome": "ERROR",
                "error": repr(exc)[:700],
            }
        )
        return False


def _feed_order(candidate: dict) -> list[tuple[str, str]]:
    route = candidate.get("route") or {}
    lane = str(
        (route.get("feed_lane") if isinstance(route, dict) else "")
        or candidate.get("feed_lane")
        or ""
    ).strip().casefold()
    ordered: list[tuple[str, str]] = []
    if lane in placsp_atom.FEEDS:
        ordered.append((lane, placsp_atom.FEEDS[lane]))
    for key, url in placsp_atom.FEEDS.items():
        if (key, url) not in ordered:
            ordered.append((key, url))
    return ordered


def _entry_match(entry: ET.Element, candidate: dict) -> tuple[bool, str]:
    wanted_cid = str(candidate.get("candidate_id") or "").strip().casefold()
    entry_cid = placsp_atom.candidate_id(entry).casefold()
    if wanted_cid and entry_cid == wanted_cid:
        return True, "candidate_id"

    route = candidate.get("route") or {}
    wanted_folder = str(
        (route.get("contract_folder_id") if isinstance(route, dict) else "")
        or candidate.get("notice_id")
        or ""
    ).strip().casefold()
    entry_folder = placsp_atom.contract_folder_id(entry).casefold()
    if wanted_folder and entry_folder and entry_folder == wanted_folder:
        wanted_title = " ".join(str(candidate.get("title") or "").casefold().split())
        entry_title = " ".join(
            str(placsp_atom.first(entry, "Name", "Title") or "").casefold().split()
        )
        if not wanted_title or not entry_title or wanted_title == entry_title:
            return True, "contract_folder_id"
    return False, ""


def _resolve_from_atom(candidate: dict, manifest: dict) -> tuple[list[str], bool, str]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Tender-Engine/15.0 public procurement research",
            "Accept": "application/atom+xml,application/xml,text/xml,*/*",
        }
    )
    started = time.monotonic()
    seen: set[str] = set()
    telemetry: list[dict] = []

    for lane, start_url in _feed_order(candidate):
        url = start_url
        page_no = 0
        while (
            url
            and url not in seen
            and page_no < PLACSP_ATOM_MAX_PAGES
            and time.monotonic() - started < PLACSP_ATOM_BUDGET
        ):
            seen.add(url)
            page_no += 1
            remaining = max(1.0, PLACSP_ATOM_BUDGET - (time.monotonic() - started))
            read_timeout = max(3, min(PLACSP_ATOM_TIMEOUT, int(remaining)))
            try:
                r = session.get(url, timeout=(5, read_timeout), allow_redirects=True)
                row = {
                    "lane": lane,
                    "page": page_no,
                    "url": url,
                    "resolved_url": r.url,
                    "http_status": r.status_code,
                    "bytes": len(r.content),
                }
                telemetry.append(row)
                if not r.ok:
                    row["outcome"] = "HTTP_ERROR"
                    break
                root = ET.fromstring(r.content)
            except Exception as exc:
                telemetry.append(
                    {
                        "lane": lane,
                        "page": page_no,
                        "url": url,
                        "outcome": "ERROR",
                        "error": repr(exc)[:600],
                    }
                )
                break

            for entry in placsp_atom.entries(root):
                matched, match_method = _entry_match(entry, candidate)
                if not matched:
                    continue
                urls = placsp_atom.document_urls(entry, r.url)
                manifest["placsp_atom_resolution"] = {
                    "lane": lane,
                    "page": page_no,
                    "feed_url": r.url,
                    "match_method": match_method,
                    "candidate_id": placsp_atom.candidate_id(entry),
                    "contract_folder_id": placsp_atom.contract_folder_id(entry),
                    "document_urls": urls,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
                manifest.setdefault("dce_method_attempts", []).append(
                    {
                        "method": "ES_PLACSP_OFFICIAL_ATOM_V15",
                        "outcome": "ENTRY_FOUND",
                        **manifest["placsp_atom_resolution"],
                        "telemetry": telemetry,
                    }
                )
                return urls, True, lane

            url = placsp_atom.next_link(root, r.url)

    manifest.setdefault("dce_method_attempts", []).append(
        {
            "method": "ES_PLACSP_OFFICIAL_ATOM_V15",
            "outcome": "ENTRY_NOT_FOUND",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "telemetry": telemetry,
        }
    )
    return [], False, ""


def _bounded_http_page(candidate: dict, out: Path, manifest: dict) -> None:
    route = candidate.get("route") or {}
    url = str(
        candidate.get("notice_url")
        or (route.get("detail_url") if isinstance(route, dict) else "")
        or ""
    ).strip()
    if not url.startswith(("http://", "https://")):
        manifest["status"] = "ROUTE_INCOMPLETE"
        return

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Tender-Engine/15.0 public procurement research",
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/zip,*/*",
        }
    )
    try:
        r = session.get(
            url,
            timeout=(5, PLACSP_HTTP_FALLBACK_TIMEOUT),
            allow_redirects=True,
        )
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append(
            {
                "method": "ES_PLACSP_BOUNDED_HTTP_V15",
                "url": url,
                "outcome": "ERROR",
                "error": repr(exc)[:700],
            }
        )
        manifest["status"] = "ERROR_RETRYABLE"
        return

    if r.ok and r.content and base.looks_like_file(r):
        manifest.setdefault("files", []).append(
            base.persist_bytes(
                out,
                base.filename_from_response(r, "placsp-document.bin"),
                r.content,
                r.url,
                r.headers.get("content-type"),
            )
        )
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    raw = html.unescape(r.text if "text" in (r.headers.get("content-type") or "").casefold() or "html" in (r.headers.get("content-type") or "").casefold() else "")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if text:
        (out / "portal_page.txt").write_text(text[:1_000_000], encoding="utf-8")

    candidate_urls: list[str] = []
    for href in re.findall(r"(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
        absolute = urljoin(r.url, html.unescape(href))
        if not absolute.startswith(("http://", "https://")):
            continue
        if placsp_atom.PLACSP_DOCUMENT_URL_RE.search(absolute) or placsp_atom.DIRECT_FILE_RE.search(absolute):
            if absolute not in candidate_urls:
                candidate_urls.append(absolute)

    downloaded = 0
    for doc_url in candidate_urls[:80]:
        if _download_placsp_url(
            doc_url,
            out,
            manifest,
            session,
            "ES_PLACSP_HTTP_DOCUMENT_V15",
        ):
            downloaded += 1
    manifest.setdefault("dce_method_attempts", []).append(
        {
            "method": "ES_PLACSP_BOUNDED_HTTP_V15",
            "url": url,
            "resolved_url": r.url,
            "http_status": r.status_code,
            "candidate_urls": candidate_urls[:80],
            "downloaded": downloaded,
        }
    )

    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
    elif r.status_code == 429 or r.status_code >= 500:
        manifest["status"] = "ERROR_RETRYABLE"
    elif v3.CAPTCHA_RE.search(text):
        manifest["status"] = "CAPTCHA_REQUIRED"
    elif r.status_code in (401, 403) or v3.AUTH_RE.search(text):
        manifest["status"] = "AUTH_REQUIRED"
    else:
        manifest["status"] = "NO_PUBLIC_FILE"


def adapter_placsp_v15(candidate: dict, out: Path, manifest: dict) -> None:
    """Official-Atom-first PLACSP resolver.

    The PLACSP syndication specification publishes procurement-document links inside
    LegalDocumentReference / TechnicalDocumentReference / AdditionalDocumentReference.
    These canonical `GetDocumentsById` URLs normally have no file extension, which
    older discovery discarded and then compensated for with slow HTML+browser probing.
    """
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Tender-Engine/15.0 public procurement research",
            "Accept": "application/pdf,application/zip,application/octet-stream,*/*",
        }
    )

    direct_urls = _candidate_urls(candidate)
    for url in direct_urls[:100]:
        _download_placsp_url(
            url,
            out,
            manifest,
            session,
            "ES_PLACSP_DISCOVERY_DOCUMENT_V15",
        )
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    atom_urls, entry_found, lane = _resolve_from_atom(candidate, manifest)
    for url in atom_urls[:100]:
        _download_placsp_url(
            url,
            out,
            manifest,
            session,
            "ES_PLACSP_ATOM_DOCUMENT_V15",
        )
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    if entry_found and not atom_urls and lane == "hosted":
        # For PLACSP-hosted profiles the official syndication entry is the
        # authoritative machine-readable representation and explicitly carries
        # PCAP/PPT/additional-document download links when they are published.
        manifest["status"] = "NO_PUBLIC_FILE"
        return

    # Aggregated regional profiles can legitimately point to a downstream system,
    # and old/historical rows may have fallen out of the live Atom window. Preserve
    # a short HTTP fallback, but never recreate the former 45s HTTP + 45s browser miss.
    _bounded_http_page(candidate, out, manifest)


base.ADAPTERS["ES_PLACSP"] = adapter_placsp_v15

if __name__ == "__main__":
    v2.main()
