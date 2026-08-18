from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v12 as v12
import dce_worker_v18 as v18  # register the complete validated V18 stack first

_OLD_HU_PUBLIC = base.ADAPTERS.get("HU_EKR_PUBLIC")
_OLD_HU = base.ADAPTERS.get("HU_EKR")

FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar)(?:$|[?#])", re.I)
DOWNLOAD_RE = re.compile(r"download|letölt|dokument|attachment|file", re.I)
DOC_SECTION_RE = re.compile(r"Közbeszerzési dokumentáció|Kijelölt dokumentumok letöltése|Download selected documents", re.I)
BUTTON_RE = re.compile(r"Kijelölt dokumentumok letöltése|Download selected documents", re.I)


def _detail_url(candidate: dict) -> str:
    route = candidate.get("route") or {}
    if isinstance(route, dict):
        for key in ("detail_url", "notice_url", "public_url"):
            value = route.get(key)
            if isinstance(value, str) and "ekr.gov.hu" in value.casefold():
                return value
    value = candidate.get("notice_url")
    return value if isinstance(value, str) and "ekr.gov.hu" in value.casefold() else ""


def _explicit_document_routes(candidate: dict) -> list[str]:
    urls: list[str] = []
    route = candidate.get("route") or {}
    if isinstance(route, dict):
        values = route.get("document_urls") or []
        if isinstance(values, list):
            urls.extend(str(u) for u in values if isinstance(u, str) and u.startswith(("http://", "https://")))
        for key in ("documents_url", "document_landing_url"):
            value = route.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                urls.append(value)
    for doc in candidate.get("documents") or []:
        value = doc.get("url") if isinstance(doc, dict) else doc
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            urls.append(value)
    return list(dict.fromkeys(urls))


def _bounded_http_probe(detail: str, out: Path, manifest: dict) -> bool:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/19.0 public procurement research",
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/zip,*/*",
    })
    try:
        response = session.get(detail, timeout=(5, 10), allow_redirects=True)
        ct = (response.headers.get("content-type") or "").lower()
        if response.ok and response.content and base.looks_like_file(response):
            manifest.setdefault("files", []).append(
                base.persist_bytes(
                    out,
                    base.filename_from_response(response, "ekr-download.bin"),
                    response.content,
                    response.url,
                    response.headers.get("content-type"),
                )
            )
            manifest.setdefault("dce_method_attempts", []).append({
                "method": "HU_EKR_BOUNDED_HTTP_V19", "url": detail,
                "resolved_url": response.url, "http_status": response.status_code,
                "outcome": "DOWNLOADED",
            })
            return True

        raw = html.unescape(response.text if "html" in ct or "text/" in ct else "")
        candidates: list[str] = []
        for href in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
            absolute = urljoin(response.url, html.unescape(href).strip())
            if not absolute.startswith(("http://", "https://")):
                continue
            host = (urlparse(absolute).hostname or "").casefold()
            if host != "ekr.gov.hu" and not host.endswith(".ekr.gov.hu"):
                continue
            if FILE_RE.search(absolute) or DOWNLOAD_RE.search(absolute):
                candidates.append(absolute)
        candidates = list(dict.fromkeys(candidates))[:12]
        downloaded = 0
        for url in candidates:
            rec = base.direct_download(url, out, session)
            if rec:
                manifest.setdefault("files", []).append(rec)
                downloaded += 1
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_BOUNDED_HTTP_V19", "url": detail,
            "resolved_url": response.url, "http_status": response.status_code,
            "candidate_urls": candidates, "downloaded": downloaded,
            "outcome": "DOWNLOADED" if downloaded else "NO_FILE",
        })
        return downloaded > 0
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_BOUNDED_HTTP_V19", "url": detail,
            "outcome": "ERROR", "error": repr(exc)[:600],
        })
        return False


def _bounded_browser_download(detail: str, out: Path, manifest: dict) -> bool:
    pw = browser = context = page = None
    body = ""
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(detail, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(1000)
        try:
            body = page.locator("body").inner_text(timeout=7000)
            (out / "portal_page.txt").write_text(body[:800_000], encoding="utf-8")
        except Exception:
            body = ""

        if not DOC_SECTION_RE.search(body):
            manifest.setdefault("dce_method_attempts", []).append({
                "method": "HU_EKR_BOUNDED_SELECTED_DOCUMENTS_V19", "url": detail,
                "outcome": "DOCUMENT_SECTION_NOT_PROVEN",
            })
            return False

        # EKR can render many checkboxes. Clicking each through Playwright can consume
        # minutes. One DOM-side pass fires the native click event for every visible,
        # enabled checkbox and returns the selected count.
        try:
            selected = int(page.locator("input[type='checkbox']").evaluate_all(
                """els => { let n=0; for (const el of els) { const s=getComputedStyle(el); const r=el.getBoundingClientRect(); const visible=s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0; if (visible && !el.disabled) { if (!el.checked) el.click(); if (el.checked) n++; } } return n; }"""
            ) or 0)
        except Exception:
            selected = 0
        if selected <= 0:
            manifest.setdefault("dce_method_attempts", []).append({
                "method": "HU_EKR_BOUNDED_SELECTED_DOCUMENTS_V19", "url": detail,
                "outcome": "NO_SELECTABLE_DOCUMENTS",
            })
            return False

        page.wait_for_timeout(500)
        controls = page.locator("button, [role='button'], a").filter(has_text=BUTTON_RE)
        for i in range(min(controls.count(), 8)):
            node = controls.nth(i)
            try:
                if not node.is_visible():
                    continue
                with page.expect_download(timeout=20000) as dl_info:
                    node.click(force=True, timeout=5000)
                manifest.setdefault("files", []).append(base.persist_download(out, dl_info.value, page.url))
                manifest.setdefault("dce_method_attempts", []).append({
                    "method": "HU_EKR_BOUNDED_SELECTED_DOCUMENTS_V19", "url": detail,
                    "selected_checkboxes": selected, "outcome": "DOWNLOADED",
                })
                return True
            except Exception as exc:
                manifest.setdefault("dce_method_attempts", []).append({
                    "method": "HU_EKR_BOUNDED_SELECTED_DOCUMENTS_V19", "url": detail,
                    "selected_checkboxes": selected, "outcome": "CONTROL_FAILED",
                    "error": repr(exc)[:400],
                })
        return False
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_BOUNDED_SELECTED_DOCUMENTS_V19", "url": detail,
            "outcome": "ERROR", "error": repr(exc)[:700],
        })
        return False
    finally:
        try:
            if page: page.close()
        except Exception: pass
        try:
            if browser: browser.close()
        except Exception: pass
        try:
            if pw: pw.stop()
        except Exception: pass


def adapter_hu_ekr_v19(candidate: dict, out: Path, manifest: dict) -> None:
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])

    # Preserve the prior validated resolver whenever discovery already supplied an
    # explicit documents route. V19 only replaces the pathological detail-only EKR
    # case that repeatedly dies at the outer worker timeout without a manifest.
    if _explicit_document_routes(candidate):
        fallback = _OLD_HU_PUBLIC or _OLD_HU
        if fallback:
            return fallback(candidate, out, manifest)

    detail = _detail_url(candidate)
    if not detail:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return

    if _bounded_http_probe(detail, out, manifest) or _bounded_browser_download(detail, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    page_text = ""
    try:
        page_text = (out / "portal_page.txt").read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    state = v12._page_state_v12(page_text)
    if state in {"AUTH_REQUIRED", "CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED"}:
        manifest["status"] = state
    else:
        # Fail closed and retryable: unlike the old path, this always leaves a
        # durable manifest rather than being externally killed after 150-170s.
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = "HU_EKR_DETAIL_ONLY_BOUNDED_V19_EXHAUSTED"


base.ADAPTERS["HU_EKR_PUBLIC"] = adapter_hu_ekr_v19
base.ADAPTERS["HU_EKR"] = adapter_hu_ekr_v19

if __name__ == "__main__":
    v2.main()
