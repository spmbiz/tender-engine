from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v11 as v11
import dce_worker_v12 as v12
import dce_worker_v18 as v18  # register the complete validated V18 stack first

_OLD_HU_PUBLIC = base.ADAPTERS.get("HU_EKR_PUBLIC")
_OLD_HU = base.ADAPTERS.get("HU_EKR")

FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar)(?:$|[?#])", re.I)
DOWNLOAD_RE = re.compile(r"download|letölt|attachment|export|(?:^|[/_-])file(?:[/_.?=&-]|$)", re.I)
EKR_API_DOWNLOAD_RE = re.compile(r"/api/publikus/.*/dokumentum-letoltes(?:/|$|[?#])", re.I)
EKR_SAFE_CONTROL_RE = re.compile(
    r"EKR\s*PDF\s*letöltés|Kijelölt dokumentumok letöltése|Download selected documents|"
    r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar)(?:\s|$)",
    re.I,
)


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


def _bounded_file_fetch(url: str, out: Path, session: requests.Session) -> dict | None:
    try:
        response = session.get(url, timeout=(4, 6), allow_redirects=True)
        if response.ok and response.content and base.looks_like_file(response):
            return base.persist_bytes(
                out,
                base.filename_from_response(response, "ekr-download.bin"),
                response.content,
                response.url,
                response.headers.get("content-type"),
            )
    except Exception:
        return None
    return None


def _bounded_http_probe(detail: str, out: Path, manifest: dict) -> bool:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/19.2 public procurement research",
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/zip,*/*",
    })
    try:
        response = session.get(detail, timeout=(4, 8), allow_redirects=True)
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
        candidates = list(dict.fromkeys(candidates))[:3]
        downloaded = 0
        for url in candidates:
            rec = _bounded_file_fetch(url, out, session)
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


def _safe_ekr_control_indices(items: list[dict]) -> list[int]:
    chosen: list[int] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("visible") or item.get("disabled"):
            continue
        hay = " ".join(str(item.get(k) or "") for k in ("text", "aria", "title")).strip()
        if not hay or v11.BLOCK_CONTROL_RE.search(hay) or not EKR_SAFE_CONTROL_RE.search(hay):
            continue
        try:
            chosen.append(int(item.get("index")))
        except Exception:
            continue
        if len(chosen) >= 10:
            break
    return chosen


def _filename_from_playwright_response(resp, ordinal: int) -> str:
    try:
        headers = resp.headers or {}
    except Exception:
        headers = {}
    cd = str(headers.get("content-disposition") or "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", cd, re.I)
    if match:
        value = match.group(1).strip().strip('"')
        if value:
            return base.safe_name(value)
    try:
        name = Path(urlparse(str(resp.url or "")).path).name
    except Exception:
        name = ""
    return base.safe_name(name or f"ekr-network-{ordinal}.bin")


def _bounded_browser_download(detail: str, out: Path, manifest: dict) -> bool:
    """Target the exact EKR public-file behavior seen in successful V18 runs.

    V18's occasional success came from public EKR file controls plus first-party
    `/dokumentum-letoltes` network responses, not from a generic selected-documents
    button. This keeps that successful path without V11's broad control/page crawl.
    """
    pw = browser = context = page = None
    body = ""
    network_responses: dict[str, object] = {}
    control_outcomes: list[dict] = []
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()

        def on_response(resp):
            try:
                url = str(resp.url or "")
                host = (urlparse(url).hostname or "").casefold()
                if host != "ekr.gov.hu" and not host.endswith(".ekr.gov.hu"):
                    return
                headers = resp.headers or {}
                ct = str(headers.get("content-type") or "").casefold()
                cd = str(headers.get("content-disposition") or "").casefold()
                if EKR_API_DOWNLOAD_RE.search(url) or "attachment" in cd or any(x in ct for x in ("application/pdf", "application/zip", "application/octet-stream")):
                    network_responses.setdefault(url, resp)
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(detail, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(1200)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        try:
            body = page.locator("body").inner_text(timeout=5000)
            if body:
                (out / "portal_page.txt").write_text(body[:800_000], encoding="utf-8")
        except Exception:
            body = ""

        controls = page.locator("button, [role='button'], a")
        try:
            items = controls.evaluate_all(
                """els => els.map((el,index) => { const s=getComputedStyle(el); const r=el.getBoundingClientRect(); return {index, text:(el.innerText||el.textContent||'').trim(), aria:el.getAttribute('aria-label')||'', title:el.getAttribute('title')||'', disabled:!!el.disabled, visible:s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0}; })"""
            )
        except Exception:
            items = []
        indices = _safe_ekr_control_indices(items or [])

        for index in indices:
            node = controls.nth(index)
            hay = ""
            try:
                item = (items or [])[index]
                hay = str((item or {}).get("text") or "")[:300]
            except Exception:
                pass
            try:
                with page.expect_download(timeout=5000) as dl_info:
                    node.click(force=True, timeout=3000)
                manifest.setdefault("files", []).append(base.persist_download(out, dl_info.value, page.url))
                control_outcomes.append({"text": hay, "outcome": "DOWNLOADED"})
            except Exception as exc:
                control_outcomes.append({"text": hay, "outcome": "NO_DIRECT_DOWNLOAD", "error": repr(exc)[:240]})
            try:
                page.wait_for_timeout(150)
            except Exception:
                pass

        network_meta: list[dict] = []
        for ordinal, (url, resp) in enumerate(list(network_responses.items())[:8], start=1):
            try:
                headers = resp.headers or {}
                content = resp.body()
                prefix = bytes(content[:8]) if content else b""
                ct = str(headers.get("content-type") or "")
                cd = str(headers.get("content-disposition") or "")
                fileish = bool(content and ("attachment" in cd.casefold() or any(x in ct.casefold() for x in ("application/pdf", "application/zip", "application/octet-stream")) or prefix.startswith(b"%PDF-") or prefix.startswith(b"PK\x03\x04")))
                network_meta.append({"url": url[:2000], "status": getattr(resp, "status", None), "content_type": ct[:200], "content_disposition": cd[:300], "bytes": len(content), "fileish": fileish})
                if fileish:
                    manifest.setdefault("files", []).append(base.persist_bytes(out, _filename_from_playwright_response(resp, ordinal), content, url, ct))
            except Exception as exc:
                network_meta.append({"url": url[:2000], "outcome": "BODY_UNAVAILABLE", "error": repr(exc)[:300]})

        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_TARGETED_NETWORK_V19",
            "url": detail,
            "safe_control_count": len(indices),
            "safe_controls": control_outcomes,
            "network_files": network_meta,
            "downloaded": len(manifest.get("files") or []),
            "outcome": "DOWNLOADED" if manifest.get("files") else "NO_FILE",
        })
        return bool(manifest.get("files"))
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_TARGETED_NETWORK_V19", "url": detail,
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
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = "HU_EKR_DETAIL_ONLY_TARGETED_V19_EXHAUSTED"


base.ADAPTERS["HU_EKR_PUBLIC"] = adapter_hu_ekr_v19
base.ADAPTERS["HU_EKR"] = adapter_hu_ekr_v19

if __name__ == "__main__":
    v2.main()
