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
# True procurement-document endpoint observed in successful V18 runs. Deliberately
# excludes `/kozbeszerzesi-hirdetmenyek/.../dokumentum-letoltes`, which is an
# announcement/notice PDF and must not satisfy the DCE gate.
EKR_API_DOWNLOAD_RE = re.compile(
    r"/api/publikus/kozbeszerzesi-eljaras-nyilvantartas/[^/?#]+/dokumentum-letoltes/[^/?#]+(?:$|[?#])",
    re.I,
)
# Only real filename-like public document controls. `EKR PDF letöltés` is a notice
# control and is intentionally excluded from DCE success.
EKR_SAFE_CONTROL_RE = re.compile(
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
        "User-Agent": "Tender-Engine/19.5 public procurement research",
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/zip,*/*",
    })
    try:
        response = session.get(detail, timeout=(4, 8), allow_redirects=True)
        ct = (response.headers.get("content-type") or "").lower()
        raw = html.unescape(response.text if "html" in ct or "text/" in ct else "")
        candidates: list[str] = []
        for href in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
            absolute = urljoin(response.url, html.unescape(href).strip())
            if not absolute.startswith(("http://", "https://")):
                continue
            host = (urlparse(absolute).hostname or "").casefold()
            if host != "ekr.gov.hu" and not host.endswith(".ekr.gov.hu"):
                continue
            # Static EKR notice PDFs are not DCE. Only explicit procedure-registry
            # document paths are eligible for the fast static pass.
            if "kozbeszerzesi-eljaras-nyilvantartas" not in absolute.casefold():
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
            "outcome": "DOWNLOADED" if downloaded else "NO_DCE_FILE",
        })
        return downloaded > 0
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_BOUNDED_HTTP_V19", "url": detail,
            "outcome": "ERROR", "error": repr(exc)[:600],
        })
        return False


def _control_priority(hay: str) -> int:
    h = str(hay or "")
    folded = h.casefold()
    if "kd_" in folded or "közbeszerzési dokumentáció" in folded:
        return 100
    if re.search(r"\.docx?(?:\s|$)", h, re.I):
        return 90
    if re.search(r"\.(?:zip|7z|rar)(?:\s|$)", h, re.I):
        return 80
    if re.search(r"\.(?:xlsx?|pptx?|csv)(?:\s|$)", h, re.I):
        return 70
    if re.search(r"\.pdf(?:\s|$)", h, re.I):
        return 60
    return 0


def _safe_ekr_control_indices(items: list[dict]) -> list[int]:
    chosen: list[tuple[int, int]] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("visible") or item.get("disabled"):
            continue
        hay = " ".join(str(item.get(k) or "") for k in ("text", "aria", "title")).strip()
        if not hay or v11.BLOCK_CONTROL_RE.search(hay) or not EKR_SAFE_CONTROL_RE.search(hay):
            continue
        priority = _control_priority(hay)
        if priority <= 0:
            continue
        try:
            chosen.append((priority, int(item.get("index"))))
        except Exception:
            continue
    chosen.sort(key=lambda row: (-row[0], row[1]))
    return [index for _, index in chosen[:6]]


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


def _dedupe_manifest_files(manifest: dict) -> int:
    """Collapse duplicate browser-download/network-response copies by SHA-256.

    Prefer the explicit EKR procedure-registry API provenance when the same bytes were
    also captured as a native browser download from the detail page.
    """
    rows = [r for r in (manifest.get("files") or []) if isinstance(r, dict)]
    chosen: dict[str, dict] = {}
    duplicate_count = 0
    for row in rows:
        sha = str(row.get("sha256") or "").strip().lower()
        key = sha or f"name:{row.get('name')}|size:{row.get('size')}"
        current = chosen.get(key)
        if current is None:
            chosen[key] = row
            continue
        duplicate_count += 1
        current_url = str(current.get("source_url") or "")
        new_url = str(row.get("source_url") or "")
        current_score = 2 if "kozbeszerzesi-eljaras-nyilvantartas" in current_url.casefold() else 1
        new_score = 2 if "kozbeszerzesi-eljaras-nyilvantartas" in new_url.casefold() else 1
        if new_score > current_score:
            chosen[key] = row
    manifest["files"] = list(chosen.values())
    if duplicate_count:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_SHA256_DEDUPE_V19",
            "duplicates_removed": duplicate_count,
            "unique_files": len(manifest["files"]),
            "outcome": "DEDUPED",
        })
    return duplicate_count


def _bounded_browser_download(detail: str, out: Path, manifest: dict) -> bool:
    """Capture only public EKR procurement-document downloads, not notice PDFs."""
    pw = browser = context = page = None
    network_responses: dict[str, object] = {}
    browser_downloads: list[object] = []
    control_outcomes: list[dict] = []
    document_surface_ready = False
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()

        def on_response(resp):
            try:
                url = str(resp.url or "")
                host = (urlparse(url).hostname or "").casefold()
                if host != "ekr.gov.hu" and not host.endswith(".ekr.gov.hu"):
                    return
                if EKR_API_DOWNLOAD_RE.search(url):
                    network_responses.setdefault(url, resp)
            except Exception:
                pass

        def on_download(download):
            try:
                browser_downloads.append(download)
            except Exception:
                pass

        page.on("response", on_response)
        page.on("download", on_download)
        page.goto(detail, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(800)
        try:
            page.wait_for_function(
                """() => { const t=(document.body && document.body.innerText)||''; return t.includes('KÖZBESZERZÉSI DOKUMENTÁCIÓ') || /\\.(zip|docx?|xlsx?|xls|pptx?|csv|7z|rar)(?:\\s|$)/i.test(t); }""",
                timeout=25000,
            )
            document_surface_ready = True
        except Exception:
            document_surface_ready = False
        try:
            body = page.locator("body").inner_text(timeout=3000)
            if body:
                (out / "portal_page.txt").write_text(body[:800_000], encoding="utf-8")
        except Exception:
            pass

        controls = page.locator("button, [role='button'], a")
        try:
            items = controls.evaluate_all(
                """els => els.map((el,index) => { const s=getComputedStyle(el); const r=el.getBoundingClientRect(); return {index, text:(el.innerText||el.textContent||'').trim(), aria:el.getAttribute('aria-label')||'', title:el.getAttribute('title')||'', disabled:!!el.disabled, visible:s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0}; })"""
            )
        except Exception:
            items = []
        indices = _safe_ekr_control_indices(items or []) if document_surface_ready else []

        for index in indices:
            node = controls.nth(index)
            hay = ""
            try:
                item = (items or [])[index]
                hay = str((item or {}).get("text") or "")[:300]
            except Exception:
                pass
            try:
                node.click(force=True, timeout=2500)
                control_outcomes.append({"text": hay, "outcome": "CLICKED"})
            except Exception as exc:
                control_outcomes.append({"text": hay, "outcome": "CLICK_FAILED", "error": repr(exc)[:240]})
            try:
                page.wait_for_timeout(650)
            except Exception:
                pass

        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass

        direct_download_meta: list[dict] = []
        for download in browser_downloads[:8]:
            try:
                name = str(download.suggested_filename or "")
                manifest.setdefault("files", []).append(base.persist_download(out, download, page.url))
                direct_download_meta.append({"suggested_filename": name[:300], "outcome": "PERSISTED"})
            except Exception as exc:
                direct_download_meta.append({"outcome": "PERSIST_FAILED", "error": repr(exc)[:300]})

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

        _dedupe_manifest_files(manifest)
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_TARGETED_DCE_NETWORK_V19",
            "url": detail,
            "document_surface_ready": document_surface_ready,
            "safe_control_count": len(indices),
            "safe_controls": control_outcomes,
            "browser_downloads": direct_download_meta,
            "network_files": network_meta,
            "downloaded": len(manifest.get("files") or []),
            "outcome": "DOWNLOADED_DCE" if manifest.get("files") else "NO_DCE_FILE",
        })
        return bool(manifest.get("files"))
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_TARGETED_DCE_NETWORK_V19", "url": detail,
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
        _dedupe_manifest_files(manifest)
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
        manifest["error"] = "HU_EKR_DETAIL_ONLY_DCE_TARGETED_V19_EXHAUSTED"


base.ADAPTERS["HU_EKR_PUBLIC"] = adapter_hu_ekr_v19
base.ADAPTERS["HU_EKR"] = adapter_hu_ekr_v19

if __name__ == "__main__":
    v2.main()
