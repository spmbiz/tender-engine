from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v17 as v17  # registers the complete validated v17 stack first

SK_FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])", re.I)
SK_STRONG_DOWNLOAD_RE = re.compile(r"generatePdfLink|download|stiah|export|priloha|attachment", re.I)
SK_PROC_RE = re.compile(r"/vyhladavanie/vyhladavanie-zakaziek/(?:detail|dokumenty)/(\d+)", re.I)

_OLD_SK_PUBLIC = base.ADAPTERS.get("SK_UVO_PUBLIC")
_OLD_SK = base.ADAPTERS.get("SK_UVO")


def _sk_documents_url(candidate: dict) -> str:
    route = candidate.get("route") or {}
    values = []
    if isinstance(route, dict):
        for key in ("documents_url", "detail_url", "notice_url", "public_url"):
            values.append(route.get(key))
    values.append(candidate.get("notice_url"))

    for value in values:
        url = str(value or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        match = SK_PROC_RE.search(url)
        if match:
            return f"https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/dokumenty/{match.group(1)}"
    return ""


def _strong_sk_urls(raw: str, base_url: str, procedure_id: str) -> list[str]:
    out: list[tuple[int, str]] = []
    for attr in re.findall(
        r"(?:href|src|action|formaction|data-url|data-href|data-download-url)\s*=\s*[\"']([^\"']+)[\"']",
        raw,
        re.I,
    ):
        url = urljoin(base_url, html.unescape(attr).strip())
        if not url.startswith(("http://", "https://")):
            continue
        host = (urlparse(url).hostname or "").casefold()
        if host not in {"uvo.gov.sk", "www.uvo.gov.sk"}:
            continue
        score = 0
        if SK_FILE_RE.search(url):
            score += 20
        if SK_STRONG_DOWNLOAD_RE.search(url):
            score += 20
        if procedure_id and f"/dokumenty/{procedure_id}" in url:
            score += 4
        # Query-only sorting, anchors and generic navigation pages are not files.
        if re.search(r"(?:[?#](?:page-content|mobile-menu|navbar-left)|[?&]sort=)", url, re.I):
            score -= 20
        if score >= 20:
            out.append((score, url))
    out.sort(key=lambda row: (-row[0], row[1]))
    return list(dict.fromkeys(url for _, url in out))[:20]


def adapter_sk_uvo_v18(candidate: dict, out: Path, manifest: dict) -> None:
    """Try UVO's exact public procedure-document page before the broad SPA cascade."""
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])
    documents_url = _sk_documents_url(candidate)
    if documents_url:
        procedure_match = SK_PROC_RE.search(documents_url)
        procedure_id = procedure_match.group(1) if procedure_match else ""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Tender-Engine/18.0 public procurement research",
                "Accept": "text/html,application/pdf,application/zip,*/*",
            }
        )
        try:
            response = session.get(documents_url, timeout=(5, 22), allow_redirects=True)
            raw = response.text if response.ok else ""
            candidates = _strong_sk_urls(raw, response.url, procedure_id) if raw else []
            downloaded = 0
            for url in candidates:
                rec = base.direct_download(url, out, session)
                if rec:
                    manifest["files"].append(rec)
                    downloaded += 1
            manifest["dce_method_attempts"].append(
                {
                    "method": "SK_UVO_STRONG_DOCUMENT_LINKS_V18",
                    "url": documents_url,
                    "resolved_url": response.url,
                    "http_status": response.status_code,
                    "candidate_urls": candidates,
                    "downloaded": downloaded,
                }
            )
            if downloaded:
                manifest["status"] = "DOWNLOADED_PUBLIC"
                return
        except Exception as exc:
            manifest["dce_method_attempts"].append(
                {
                    "method": "SK_UVO_STRONG_DOCUMENT_LINKS_V18",
                    "url": documents_url,
                    "outcome": "ERROR",
                    "error": repr(exc)[:700],
                }
            )

    fallback = _OLD_SK_PUBLIC or _OLD_SK
    if fallback:
        return fallback(candidate, out, manifest)
    manifest["status"] = "ROUTE_INCOMPLETE"


base.ADAPTERS["SK_UVO_PUBLIC"] = adapter_sk_uvo_v18
base.ADAPTERS["SK_UVO"] = adapter_sk_uvo_v18

if __name__ == "__main__":
    v2.main()
