from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v11 as v11
import dce_worker_v12 as v12

# Complete the promotion of the known TED WAVE2 generic-host backlog into named
# vendor/country families. EE_RHR deliberately points at the existing v10 dedicated
# Estonia resolver rather than the generic browser adapter.
EXTRA_HOST_PORTALS = {
    "www.tenderned.nl": "NL_TENDERNED_PUBLIC",
    "tenderned.nl": "NL_TENDERNED_PUBLIC",
    "www.simap.ch": "CH_SIMAP_PUBLIC",
    "simap.ch": "CH_SIMAP_PUBLIC",
    "riigihanked.riik.ee": "EE_RHR",
    "bi-medien.de": "DE_BI_MEDIEN",
    "www.bi-medien.de": "DE_BI_MEDIEN",
    "ezamowienia.gov.pl": "PL_EZAMOWIENIA",
    "www.ezamowienia.gov.pl": "PL_EZAMOWIENIA",
    "lajunta.es": "ES_LAJUNTA",
    "www.lajunta.es": "ES_LAJUNTA",
    "www.evergabe.de": "DE_EVERGABE_DE",
    "evergabe.de": "DE_EVERGABE_DE",
    "lwl.org": "DE_LWL",
    "www.lwl.org": "DE_LWL",
    "cloud.3p.eu": "THREEP_CLOUD",
    "bip.slaskie.pl": "PL_BIP_SLASKIE",
    "www.comdia.com": "COMDIA_PUBLIC",
    "comdia.com": "COMDIA_PUBLIC",
}
EXTRA_SUFFIX_PORTALS = (
    (".e-marchespublics.com", "FR_E_MARCHESPUBLICS"),
)

_old_portal_for_url = v11.portal_for_url


def portal_for_url_v13(url: str) -> str | None:
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").casefold()
        path = parsed.path.casefold()
    except Exception:
        return _old_portal_for_url(url)
    if host in EXTRA_HOST_PORTALS:
        return EXTRA_HOST_PORTALS[host]
    for suffix, portal in EXTRA_SUFFIX_PORTALS:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return portal
    if "/netserver/" in path or "tenderingproceduredetails" in str(url).casefold() or "publicationcontrollerservlet" in str(url).casefold():
        return "NETSERVER_PUBLIC"
    return _old_portal_for_url(url)


v11.portal_for_url = portal_for_url_v13

# e-Avrop explicitly instructs users to click 'hämta & Bevaka' before reading the
# files. Treat this conservatively as an interest/watch gate; never auto-click it.
EAVROP_INTEREST_RE = re.compile(r"h[aä]mta\s*&\s*bevaka.{0,160}(?:l[aä]sa|dokument)", re.I | re.S)
_old_page_state = v11._page_state


def _page_state_v13(body: str, status: int | None = None) -> str:
    if EAVROP_INTEREST_RE.search(body or ""):
        return "INTEREST_RECORDING_REQUIRED"
    return _old_page_state(body, status)


v11._page_state = _page_state_v13


def resolve_ted_candidate_v13(candidate: dict, timeout: int = 60) -> dict:
    result = v11.resolve_ted_candidate_v11(candidate, timeout=timeout)
    for item in result.get("downstream") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        portal = portal_for_url_v13(url)
        if portal:
            item["portal"] = portal
            route = item.get("route") if isinstance(item.get("route"), dict) else {}
            route.update({
                "detail_url": route.get("detail_url") or url,
                "downstream_host": (urlparse(url).hostname or "").casefold(),
                "portal_family_v13": portal,
            })
            # Slovak UVO notices consistently publish an unrestricted documents URL
            # /dokumenty/{procedure_id}. If TED only exposes the detail/submission URL,
            # derive the official public documents endpoint deterministically.
            if portal in {"SK_UVO", "SK_UVO_PUBLIC"}:
                m = re.search(r"/(?:detail|dokumenty)/(\d+)", url)
                if m:
                    route["documents_url"] = f"https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/dokumenty/{m.group(1)}"
            item["route"] = route
    return result


v2.resolve_ted_candidate = resolve_ted_candidate_v13

DOC_TAB_RE = re.compile(
    r"^(?:documents?|documenten|dokumente|dokumenty|documenta(?:tion|ție)?|documentaci[oó]|"
    r"documentaci[oó]n|documenta[cç][aã]o|załączniki|prilozi|bilag|vedlegg|"
    r"upphandlingsdokument|vergabedokumente|vergabeunterlagen)$",
    re.I,
)
FILE_NAME_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar|rtf|xml)(?:$|\s)", re.I)


def _second_stage_public_documents(candidate: dict, out: Path, manifest: dict) -> bool:
    """Re-open a public page and expand one safe documents tab before file clicks.

    This is intentionally separate from the first-pass adapter: many SPAs render a
    'Documents' tab first, then inject file controls. No auth, register, interest,
    participation, question, submission or bid control is clicked.
    """
    route = candidate.get("route") or {}
    detail = str(route.get("documents_url") or route.get("detail_url") or candidate.get("notice_url") or "")
    if not detail.startswith(("http://", "https://")):
        return False
    if manifest.get("status") in {"CAPTCHA_REQUIRED", "AUTH_REQUIRED", "INTEREST_RECORDING_REQUIRED"}:
        return False

    pw = browser = context = page = None
    try:
        pw, browser, context = v11.v2.optimized_browser_context()
        page = context.new_page()
        page.goto(detail, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1600)
        try:
            page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass

        # Expand at most two document-only tabs/accordions.
        expanded = []
        controls = page.locator("button, [role='button'], a")
        for i in range(min(controls.count(), 160)):
            if len(expanded) >= 2:
                break
            node = controls.nth(i)
            try:
                if not node.is_visible():
                    continue
                txt = re.sub(r"\s+", " ", node.inner_text(timeout=1000) or "").strip()
                if not DOC_TAB_RE.match(txt):
                    continue
                if v11.BLOCK_CONTROL_RE.search(txt):
                    continue
                node.click(force=True, timeout=3500)
                page.wait_for_timeout(900)
                expanded.append(txt[:120])
            except Exception:
                continue

        downloaded = 0
        seen = set()
        # Direct anchors first.
        anchors = page.locator("a[href]").evaluate_all("els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim()}))")
        for item in anchors or []:
            href = str((item or {}).get("href") or "").strip()
            txt = str((item or {}).get("text") or "").strip()
            if not href.startswith(("http://", "https://")):
                continue
            if not (FILE_NAME_RE.search(txt) or v11.FILE_URL_RE.search(href)):
                continue
            if v11.BLOCK_CONTROL_RE.search(txt):
                continue
            if href in seen:
                continue
            seen.add(href)
            rec = base.direct_download(href, out)
            if rec:
                manifest.setdefault("files", []).append(rec)
                downloaded += 1
            if downloaded >= 25:
                break

        # Then file-name buttons emitted by SPAs.
        if downloaded < 25:
            controls = page.locator("button, [role='button'], a")
            for i in range(min(controls.count(), 260)):
                if downloaded >= 25:
                    break
                node = controls.nth(i)
                try:
                    if not node.is_visible():
                        continue
                    txt = re.sub(r"\s+", " ", node.inner_text(timeout=1000) or "").strip()
                    if not FILE_NAME_RE.search(txt) or v11.BLOCK_CONTROL_RE.search(txt):
                        continue
                    try:
                        with page.expect_download(timeout=6500) as dl:
                            node.click(force=True, timeout=4000)
                        manifest.setdefault("files", []).append(base.persist_download(out, dl.value, page.url))
                        downloaded += 1
                    except Exception:
                        continue
                except Exception:
                    continue

        manifest.setdefault("dce_method_attempts", []).append({
            "method": "PUBLIC_DOCUMENTS_SECOND_STAGE_V13",
            "url": detail,
            "expanded_tabs": expanded,
            "downloaded": downloaded,
        })
        return downloaded > 0
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "PUBLIC_DOCUMENTS_SECOND_STAGE_V13", "url": detail,
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


def adapter_public_spa_v13(candidate: dict, out: Path, manifest: dict):
    v12.adapter_public_spa_v12(candidate, out, manifest)
    if manifest.get("files"):
        return
    if _second_stage_public_documents(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"


EXTRA_PUBLIC_PORTALS = (set(EXTRA_HOST_PORTALS.values()) | {p for _, p in EXTRA_SUFFIX_PORTALS} | {"NETSERVER_PUBLIC"}) - {"EE_RHR"}
v11.V11_PUBLIC_PORTALS.update(EXTRA_PUBLIC_PORTALS)
for portal in sorted(v11.V11_PUBLIC_PORTALS):
    if portal == "EE_RHR":
        continue
    base.ADAPTERS[portal] = adapter_public_spa_v13
v11.matrix.BROWSER_PORTALS.update(EXTRA_PUBLIC_PORTALS)
v11.matrix.SUPPORTED.update(EXTRA_PUBLIC_PORTALS)

if __name__ == "__main__":
    v2.main()
