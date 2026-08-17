from __future__ import annotations

import re
from pathlib import Path

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v11 as v11

# Global sign-in navigation is common on otherwise public procurement pages. Only
# treat authentication as a DCE barrier when HTTP says so or the page text states
# that authentication/registration is required for the documents themselves.
AUTH_GATE_RE = re.compile(
    r"(?:login|log in|sign in|se connecter|connexion|anmelden|bejelentkez|zaloguj|accedi)"
    r".{0,120}(?:required|necessar|to download|for documents?|pour (?:t[eé]l[eé]charger|acc[eé]der)|"
    r"erforderlich|zum herunterladen|dokument|szükséges|letölt|wymagan|pobierz|necessario|scaric)|"
    r"(?:documents?|attachments?|download|dce|dokument|unterlag|letölt|załącz|allegat)"
    r".{0,120}(?:login|log in|sign in|se connecter|connexion|anmelden|bejelentkez|zaloguj|accedi)",
    re.I | re.S,
)
INTEREST_GATE_RE = re.compile(
    r"(?:record|register|express|manifest).{0,80}(?:interest|int[eé]r[eê]t).{0,160}(?:document|download|access|dce)|"
    r"(?:document|download|access|dce).{0,160}(?:record|register|express|manifest).{0,80}(?:interest|int[eé]r[eê]t)",
    re.I | re.S,
)


def _page_state_v12(body: str, status: int | None = None) -> str:
    text = body or ""
    if v11.CAPTCHA_RE.search(text):
        return "CAPTCHA_REQUIRED"
    if INTEREST_GATE_RE.search(text):
        return "INTEREST_RECORDING_REQUIRED"
    if status in (401, 403) or AUTH_GATE_RE.search(text):
        return "AUTH_REQUIRED"
    return "GENERIC_PUBLIC_PAGE_UNRESOLVED"


v11._page_state = _page_state_v12


def _ekr_selected_document_download(candidate: dict, out: Path, manifest: dict) -> bool:
    """Public EKR helper for the explicit 'download selected documents' UI.

    It operates only on anonymous procurement-document controls. It never opens a
    login/registration flow or submits/changes a tender response.
    """
    route = candidate.get("route") or {}
    detail = str(route.get("detail_url") or candidate.get("notice_url") or "")
    if "ekr.gov.hu" not in detail.casefold():
        return False
    pw = browser = context = page = None
    try:
        pw, browser, context = v11.v2.optimized_browser_context()
        page = context.new_page()
        page.goto(detail, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2200)
        try:
            page.wait_for_load_state("networkidle", timeout=9000)
        except Exception:
            pass
        body = page.locator("body").inner_text(timeout=15000)
        if not re.search(r"Közbeszerzési dokumentáció|Kijelölt dokumentumok letöltése", body, re.I):
            return False

        # EKR renders one checkbox per downloadable procurement document. Select
        # visible enabled boxes only after the procurement-document section is proven.
        checked = 0
        boxes = page.locator("input[type='checkbox']")
        for i in range(min(boxes.count(), 120)):
            box = boxes.nth(i)
            try:
                if box.is_visible() and box.is_enabled() and not box.is_checked():
                    box.check(force=True, timeout=2500)
                    checked += 1
            except Exception:
                continue
        if not checked:
            return False

        controls = page.locator("button, [role='button'], a")
        for i in range(min(controls.count(), 120)):
            node = controls.nth(i)
            try:
                if not node.is_visible():
                    continue
                text = re.sub(r"\s+", " ", node.inner_text(timeout=1000) or "").strip()
                if not re.search(r"Kijelölt dokumentumok letöltése|Download selected documents", text, re.I):
                    continue
                with page.expect_download(timeout=25000) as dl:
                    node.click(force=True, timeout=5000)
                manifest.setdefault("files", []).append(base.persist_download(out, dl.value, page.url))
                manifest.setdefault("dce_method_attempts", []).append({
                    "method": "HU_EKR_SELECTED_DOCUMENTS_V12",
                    "url": detail,
                    "selected_checkboxes": checked,
                    "outcome": "DOWNLOADED",
                })
                return True
            except Exception as exc:
                manifest.setdefault("dce_method_attempts", []).append({
                    "method": "HU_EKR_SELECTED_DOCUMENTS_V12",
                    "url": detail,
                    "selected_checkboxes": checked,
                    "outcome": "NO_DOWNLOAD",
                    "error": repr(exc)[:500],
                })
                continue
        return False
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "HU_EKR_SELECTED_DOCUMENTS_V12", "url": detail,
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


def adapter_public_spa_v12(candidate: dict, out: Path, manifest: dict):
    v11.adapter_public_spa_v11(candidate, out, manifest)
    if manifest.get("files"):
        return
    portal = str(candidate.get("portal") or candidate.get("portal_key") or candidate.get("source") or "").upper()
    if portal in {"HU_EKR", "HU_EKR_PUBLIC"} and manifest.get("status") not in {"CAPTCHA_REQUIRED"}:
        if _ekr_selected_document_download(candidate, out, manifest):
            manifest["status"] = "DOWNLOADED_PUBLIC"


# Rebind only the v11 expanded generic/named public families. Dedicated v10
# resolvers (SAM, PCS, Estonia RHR, World Bank, etc.) stay untouched.
for portal in sorted(v11.V11_PUBLIC_PORTALS):
    base.ADAPTERS[portal] = adapter_public_spa_v12

if __name__ == "__main__":
    v2.main()
