from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

import dce_worker as base
import dce_worker_v2 as v2

FILE_OR_DOWNLOAD_RE = re.compile(
    r"(?:\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])|"
    r"download|document|dokument|unterlagen|vergabeunterlag|attachment|piece|pi[eè]ce|"
    r"telecharg|pliego|anexo|annex|dce)",
    re.I,
)
CAPTCHA_RE = re.compile(r"captcha|security code|code de sécurité|verification code|recaptcha", re.I)
AUTH_RE = re.compile(r"\blog[ -]?in\b|sign in|se connecter|connexion|anmelden|registrieren|identification", re.I)


def _public_page_adapter(candidate: dict, out: Path, manifest: dict):
    route = candidate.get("route") or {}
    detail_url = route.get("detail_url") or candidate.get("notice_url")
    if not detail_url:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/3.0 public procurement research"})
    page_text = ""
    candidate_urls: list[str] = []

    # Fast HTTP pass first. Many procurement portals render document anchors server-side.
    try:
        r = session.get(detail_url, timeout=45, allow_redirects=True)
        if r.ok:
            page_text = html.unescape(r.text)
            for href in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", page_text, re.I):
                absolute = urljoin(r.url, html.unescape(href))
                if absolute.startswith(("http://", "https://")) and FILE_OR_DOWNLOAD_RE.search(absolute):
                    candidate_urls.append(absolute)
    except Exception as exc:
        manifest["error"] = repr(exc)

    # Browser pass discovers JS-rendered anchors but does not bypass login/CAPTCHA.
    if not candidate_urls:
        pw = browser = context = page = None
        try:
            pw, browser, context = v2.optimized_browser_context()
            page = context.new_page()
            page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(800)
            try:
                page_text = page.locator("body").inner_text(timeout=15000)
                (out / "portal_page.txt").write_text(page_text[:2_000_000], encoding="utf-8")
            except Exception:
                pass
            anchors = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(a => ({href:a.href, text:(a.innerText||a.textContent||'').trim()}))",
            )
            for a in anchors or []:
                href = str((a or {}).get("href") or "")
                text = str((a or {}).get("text") or "")
                if href.startswith(("http://", "https://")) and FILE_OR_DOWNLOAD_RE.search(href + " " + text):
                    candidate_urls.append(href)
        except Exception as exc:
            if not manifest.get("error"):
                manifest["error"] = repr(exc)
        finally:
            try:
                if page:
                    page.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if pw:
                    pw.stop()
            except Exception:
                pass

    # Deterministic dedupe and bounded download attempts.
    unique = []
    seen = set()
    for url in candidate_urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    manifest["public_document_candidates"] = unique[:50]
    for url in unique[:30]:
        rec = base.direct_download(url, out, session)
        if rec:
            manifest["files"].append(rec)

    if manifest["files"]:
        manifest["status"] = "DOWNLOADED_PUBLIC"
    elif CAPTCHA_RE.search(page_text or ""):
        manifest["status"] = "CAPTCHA_REQUIRED"
    elif AUTH_RE.search(page_text or ""):
        manifest["status"] = "AUTH_REQUIRED"
    else:
        manifest["status"] = "NO_PUBLIC_FILE"


for portal in ("DE_DTVP", "FR_AWS", "BE_EPROC", "ES_PLACSP", "DE_EVERGABE"):
    base.ADAPTERS[portal] = _public_page_adapter


if __name__ == "__main__":
    v2.main()
