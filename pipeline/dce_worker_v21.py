from __future__ import annotations

import copy
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v13 as v13
import dce_worker_v20 as v20  # registers the complete validated V20 stack


NEN_DETAIL_RE = re.compile(r"(?P<prefix>/verejne-zakazky/detail-zakazky/(?P<id>N\d{3}-\d{2}-V\d{9}))", re.I)
NEN_DOWNLOAD_ALL_RE = re.compile(r"(?:st[aá]hnout\s+v[sš]echny\s+p[řr][ií]lohy|download\s+all\s+attachments)", re.I)
NEN_FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar|rtf|xml|cer)(?:$|[?#])", re.I)


def nen_documents_url(candidate: dict) -> str | None:
    """Return the canonical public NEN procurement-document tab for a candidate."""
    route = candidate.get("route") or {}
    candidates = []
    for value in (
        route.get("documents_url"),
        route.get("detail_url"),
        route.get("public_url"),
        route.get("source_url"),
        candidate.get("notice_url"),
    ):
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            candidates.append(value)
    for url in candidates:
        try:
            parsed = urlparse(url)
        except Exception:
            continue
        if (parsed.hostname or "").casefold() != "nen.nipez.cz":
            continue
        match = NEN_DETAIL_RE.search(parsed.path)
        if not match:
            continue
        base_path = match.group("prefix").rstrip("/")
        return f"{parsed.scheme or 'https'}://nen.nipez.cz{base_path}/zadavaci-dokumentace"
    return None


def _try_nen_download_all(candidate: dict, documents_url: str, out: Path, manifest: dict) -> bool:
    """Click only NEN's public procurement-document download controls.

    No authentication, registration, participation, interest-recording or bid
    controls are touched. Direct file anchors are attempted before the public
    "download all attachments" control.
    """
    pw = browser = context = page = None
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/21.0 public procurement research"})
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(documents_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1200)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        body = page.locator("body").inner_text(timeout=10000)
        (out / "portal_page_nen.txt").write_text(body[:1_000_000], encoding="utf-8")

        # Public file anchors first; these avoid browser download overhead when NEN
        # renders direct attachment URLs.
        anchors = page.locator("a[href]").evaluate_all(
            "els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim()}))"
        )
        seen = set()
        for item in anchors or []:
            href = str((item or {}).get("href") or "").strip()
            text = str((item or {}).get("text") or "").strip()
            if not href.startswith(("http://", "https://")):
                continue
            if href in seen or not NEN_FILE_RE.search(f"{href} {text}"):
                continue
            seen.add(href)
            rec = base.direct_download(href, out, session)
            manifest.setdefault("dce_method_attempts", []).append({
                "method": "CZ_NEN_DIRECT_ATTACHMENT_V21",
                "url": href,
                "outcome": "DOWNLOADED" if rec else "NOT_FILE",
            })
            if rec:
                manifest.setdefault("files", []).append(rec)

        if manifest.get("files"):
            return True

        # NEN exposes a public aggregate control on procurement-document pages.
        controls = page.locator("button, [role='button'], a")
        for i in range(min(controls.count(), 180)):
            node = controls.nth(i)
            try:
                if not node.is_visible():
                    continue
                text = re.sub(r"\s+", " ", node.inner_text(timeout=1000) or "").strip()
                aria = str(node.get_attribute("aria-label") or "")
                title = str(node.get_attribute("title") or "")
                hay = " ".join(x for x in (text, aria, title) if x).strip()
                if not NEN_DOWNLOAD_ALL_RE.search(hay):
                    continue
                # Explicitly reject any accidental auth/participation control.
                if v13.v11.BLOCK_CONTROL_RE.search(hay):
                    continue
                try:
                    with page.expect_download(timeout=12000) as dl:
                        node.click(force=True, timeout=5000)
                    rec = base.persist_download(out, dl.value, documents_url)
                    manifest.setdefault("files", []).append(rec)
                    manifest.setdefault("dce_method_attempts", []).append({
                        "method": "CZ_NEN_DOWNLOAD_ALL_V21",
                        "url": documents_url,
                        "control": hay[:200],
                        "outcome": "DOWNLOADED",
                    })
                    return True
                except Exception as exc:
                    manifest.setdefault("dce_method_attempts", []).append({
                        "method": "CZ_NEN_DOWNLOAD_ALL_V21",
                        "url": documents_url,
                        "control": hay[:200],
                        "outcome": "NO_DOWNLOAD",
                        "error": repr(exc)[:500],
                    })
            except Exception:
                continue
        return False
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


def adapter_cz_nen_v21(candidate: dict, out: Path, manifest: dict):
    manifest.setdefault("dce_method_attempts", [])
    manifest.setdefault("files", [])
    documents_url = nen_documents_url(candidate)
    if not documents_url:
        # Preserve the exact V20 behavior when the candidate is not a canonical
        # NEN public-detail route.
        v13.adapter_public_spa_v13(candidate, out, manifest)
        return

    trial = copy.deepcopy(candidate)
    route = dict(trial.get("route") or {})
    route["documents_url"] = documents_url
    route["detail_url"] = documents_url
    route["nen_documents_url_v21"] = documents_url
    trial["route"] = route
    trial["notice_url"] = documents_url
    manifest["cz_nen_documents_url"] = documents_url

    # Reuse the validated V13 public SPA stack against the *right* NEN tab first.
    v13.adapter_public_spa_v13(trial, out, manifest)
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    # If the generic SPA pass found no file, use one narrowly scoped NEN control.
    if manifest.get("status") not in {"AUTH_REQUIRED", "CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED"}:
        if _try_nen_download_all(trial, documents_url, out, manifest):
            manifest["status"] = "DOWNLOADED_PUBLIC"
            return

    # Keep an honest unresolved/barrier status from the underlying stack.
    if not manifest.get("status"):
        manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"


for _portal in ("CZ_NIPEZ", "CZ_NIPEZ_PUBLIC"):
    base.ADAPTERS[_portal] = adapter_cz_nen_v21


if __name__ == "__main__":
    v20.install_http_probe_guard()
    v2.main()
