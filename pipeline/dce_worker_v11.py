from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import build_matrix as matrix
import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v4 as v4
import dce_worker_v10 as v10  # noqa: F401 - registers the proven v10 stack first
import ted_resolver as ted_base

FILE_CT_RE = re.compile(r"(?:application/(?:pdf|zip|octet-stream|msword|vnd\.)|text/csv)", re.I)
FILE_URL_RE = re.compile(r"(?:\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar)(?:$|[?#])|download|attachment|document|dokument|unterlag|pliego|anexo|annex|dce|piece|pi[eè]ce|bilag|vedlegg)", re.I)
DOC_CONTROL_RE = re.compile(
    r"download|documents?|attachments?|tender files?|procurement documents?|dossier|dce|"
    r"dokument|unterlag|vergab|ausschreibungsunterlag|pliego|anexo|annex|bilag|vedlegg|"
    r"let[oö]lt|dokumentum|документ|изтег|descarc|documenta|dokumenti|preuz|stiah|"
    r"datoteke|prilozi|priloge|załącz|pobierz|scarica|allegat|baixar|ficheiros?",
    re.I,
)
BLOCK_CONTROL_RE = re.compile(
    r"login|log in|sign in|register|registration|record interest|express interest|participat|"
    r"submit|submission|apply|offer|bid|tender response|se connecter|connexion|s'inscrire|"
    r"anmelden|registrier|prijav|prihl[aá]s|bejelentkez|regisztr|вход|регист|autentific|"
    r"inregistr|inregistrare|zaloguj|rejestr|accedi|registrati",
    re.I,
)
CAPTCHA_RE = re.compile(r"captcha|recaptcha|security code|verification code|code de sécurité", re.I)
AUTH_RE = re.compile(r"\blog[ -]?in\b|sign in|se connecter|connexion|anmelden|prijava|prihlás|bejelentkez|вход|autentific|zaloguj|accedi", re.I)
INTEREST_RE = re.compile(r"record(?:ing)? (?:your )?interest|register interest|express interest|manifester.*int[eé]r[eê]t", re.I)

# High-volume TED downstream families that were still collapsed into GENERIC_PUBLIC_PAGE
# or TED_PUBLIC_PAGE_FAST. Named route keys make backlog telemetry actionable and let us
# evolve one vendor/country family without perturbing the rest of the resolver stack.
EXACT_HOST_PORTALS = {
    "ec.europa.eu": "EU_FUNDING_TENDERS",
    "commission.europa.eu": "EU_FUNDING_TENDERS",
    "www.publicprocurement.be": "BE_EPROC_V11",
    "publicprocurement.be": "BE_EPROC_V11",
    "eprocurement.gov.be": "BE_EPROC_V11",
    "s2c.mercell.com": "MERCELL_S2C",
    "permalink.mercell.com": "MERCELL_PUBLIC",
    "community.vortal.biz": "VORTAL_PUBLIC",
    "eu.eu-supply.com": "EU_SUPPLY_PUBLIC",
    "annonser.clira.io": "SE_CLIRA",
    "www.e-avrop.com": "SE_EAVROP",
    "e-avrop.com": "SE_EAVROP",
    "tendsign.com": "SE_TENDSIGN",
    "www.kommersannons.se": "SE_KOMMERSANNONS",
    "app.artifik.no": "NO_ARTIFIK",
    "app.eop.bg": "BG_EOP_PUBLIC",
    "e-licitatie.ro": "RO_SEAP_PUBLIC",
    "ekr.gov.hu": "HU_EKR_PUBLIC",
    "eojn.hr": "HR_EOJN_PUBLIC",
    "www.uvo.gov.sk": "SK_UVO_PUBLIC",
    "www.eis.gov.lv": "LV_EIS_PUBLIC",
    "nen.nipez.cz": "CZ_NIPEZ_PUBLIC",
    "www.egordion.cz": "CZ_EGORDION",
    "zakazky.spucr.cz": "CZ_ZAKAZKY_VENDOR",
    "nepps-search.eprocurement.gov.gr": "GR_EPPS_PUBLIC",
    "nepps.eprocurement.gov.gr": "GR_EPPS_PUBLIC",
    "portal.eprocurement.gov.gr": "GR_EPPS_PUBLIC",
    "www.achatpublic.com": "FR_ACHATPUBLIC",
    "marches.maximilien.fr": "FR_MAXIMILIEN",
    "www.marches-securises.fr": "FR_MARCHES_SECUR",
    "marches-securises.fr": "FR_MARCHES_SECUR",
    "plateforme.alsacemarchespublics.eu": "FR_ALSACE_MARCHES",
    "oisehabitatmarchespublics.safetender.com": "FR_SAFETENDER",
    "contractaciopublica.cat": "ES_CATALONIA_PUBLIC",
    "contractaciopublica.gencat.cat": "ES_CATALONIA_PUBLIC",
    "www.contratacion.euskadi.eus": "ES_EUSKADI_PUBLIC",
    "juntadeandalucia.es": "ES_ANDALUCIA_PUBLIC",
    "contratos-publicos.comunidad.madrid": "ES_MADRID_PUBLIC",
    "hacienda.navarra.es": "ES_NAVARRA_PUBLIC",
    "www.acquistinretepa.it": "IT_ACQUISTINRETEPA",
    "app.albofornitori.it": "IT_ALBOFORNITORI",
    "www.bandi-altoadige.it": "IT_ALTOADIGE",
    "www.acingov.pt": "PT_ACINGOV",
    "gv.vergabeportal.at": "AT_VERGABEPORTAL",
    "bbg.vergabeportal.at": "AT_VERGABEPORTAL",
    "fwp.vergabeportal.at": "AT_VERGABEPORTAL",
    "www.subreport.de": "DE_SUBREPORT",
    "www.vergabe24.de": "DE_VERGABE24",
    "www.tender24.de": "DE_TENDER24",
    "www.evergabe.nrw.de": "DE_EVERGABE_NRW",
    "bieterzugang.deutsche-evergabe.de": "DE_DEUTSCHE_EVERGABE",
    "www.meinauftrag.rib.de": "DE_RIB",
    "ausschreibungen.landbw.de": "DE_LANDBW",
    "ausschreibungen.giz.de": "DE_GIZ",
    "ausschreibungen.kfw.de": "DE_KFW",
    "vergabeplattform.bwi.de": "DE_BWI",
    "landesverwaltung.vergabe.rlp.de": "DE_RLP",
    "www.vergabe.metropoleruhr.de": "DE_METROPOLERUHR",
    "bieterportal.pd-g.e-va.eu": "DE_EVA",
    "www.deutsches-ausschreibungsblatt.de": "DE_DAB",
}
SUFFIX_PORTALS = (
    (".platformazakupowa.pl", "PL_PLATFORMZAKUPOWA"),
    (".ezamawiajacy.pl", "PL_EZAMAWIAJACY"),
    (".logintrade.net", "PL_LOGINTRADE"),
    (".eb2b.com.pl", "PL_EB2B"),
    (".safetender.com", "SAFETENDER_PUBLIC"),
    (".vemap.com", "VEMAP_PUBLIC"),
    (".tuttogare.it", "IT_TUTTOGARE"),
    (".traspare.com", "IT_TRASPARE"),
    (".maggiolicloud.it", "IT_MAGGIOLI"),
    (".e-pal.it", "IT_EPAL"),
)


def portal_for_url(url: str) -> str | None:
    try:
        host = (urlparse(str(url or "")).hostname or "").casefold()
    except Exception:
        return None
    if host in EXACT_HOST_PORTALS:
        return EXACT_HOST_PORTALS[host]
    for suffix, portal in SUFFIX_PORTALS:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return portal
    return None


def _route(url: str, portal: str) -> dict:
    return {"detail_url": url, "downstream_host": (urlparse(url).hostname or "").casefold(), "portal_family_v11": portal}


def resolve_ted_candidate_v11(candidate: dict, timeout: int = 60) -> dict:
    result = ted_base.resolve_ted_candidate(candidate, timeout=timeout)
    for item in result.get("downstream") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        portal = portal_for_url(url)
        if portal:
            item["portal"] = portal
            old = item.get("route") if isinstance(item.get("route"), dict) else {}
            item["route"] = {**old, **_route(url, portal)}
    return result


def _fileish_headers(headers: dict, url: str = "") -> bool:
    ct = str((headers or {}).get("content-type") or "")
    cd = str((headers or {}).get("content-disposition") or "")
    return bool(FILE_CT_RE.search(ct) or "attachment" in cd.casefold() or FILE_URL_RE.search(url))


def _page_state(body: str, status: int | None = None) -> str:
    text = body or ""
    if CAPTCHA_RE.search(text):
        return "CAPTCHA_REQUIRED"
    if INTEREST_RE.search(text):
        return "INTEREST_RECORDING_REQUIRED"
    if status in (401, 403) or AUTH_RE.search(text):
        return "AUTH_REQUIRED"
    return "GENERIC_PUBLIC_PAGE_UNRESOLVED"


def adapter_public_spa_v11(candidate: dict, out: Path, manifest: dict):
    """Anonymous SPA/public-page DCE recovery with safe DOM + network discovery.

    This adapter never signs in, creates an account, records interest, submits a bid,
    or bypasses CAPTCHA. It only follows publicly rendered document/download controls.
    """
    manifest.setdefault("dce_method_attempts", [])
    manifest.setdefault("files", [])
    if v4._attempt_direct(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    route_urls = [(m, u) for m, u in v4._route_urls(candidate) if m != "DIRECT_DOCUMENT"]
    if not route_urls:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/11.0 public procurement research", "Accept": "text/html,application/xhtml+xml,application/pdf,application/zip,*/*"})
    states: list[str] = []

    # Fast server-rendered pass, including forms/data URLs that older anchor-only
    # generic adapters miss.
    for method, url in route_urls[:8]:
        try:
            r = session.get(url, timeout=35, allow_redirects=True)
            raw = html.unescape(r.text if "html" in (r.headers.get("content-type") or "").casefold() or "text/" in (r.headers.get("content-type") or "").casefold() else "")
            text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
            text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", html.unescape(text)).strip()
            if text:
                (out / "portal_page_http.txt").write_text(text[:1_000_000], encoding="utf-8")
            candidates = []
            for attr in re.findall(r"(?:href|src|action|data-url|data-href|data-download-url)\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
                absolute = urljoin(r.url, html.unescape(attr))
                if absolute.startswith(("http://", "https://")) and FILE_URL_RE.search(absolute):
                    candidates.append(absolute)
            candidates = list(dict.fromkeys(candidates))[:50]
            downloaded = 0
            for candidate_url in candidates:
                rec = base.direct_download(candidate_url, out, session)
                if rec:
                    manifest["files"].append(rec)
                    downloaded += 1
            manifest["dce_method_attempts"].append({"method": f"V11_HTTP_{method}", "url": url, "resolved_url": r.url, "http_status": r.status_code, "candidate_urls": candidates[:30], "downloaded": downloaded})
            if manifest["files"]:
                manifest["status"] = "DOWNLOADED_PUBLIC"
                return
            states.append(_page_state(text, r.status_code))
        except Exception as exc:
            manifest["dce_method_attempts"].append({"method": f"V11_HTTP_{method}", "url": url, "outcome": "ERROR", "error": repr(exc)[:600]})

    # JS-rendered pass. We collect anonymous XHR/file responses and only click
    # controls whose visible text is document/download related and not auth/bid related.
    pw = browser = context = page = None
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        network_urls: list[str] = []
        network_meta: list[dict] = []

        def on_response(resp):
            try:
                url = str(resp.url or "")
                headers = resp.headers or {}
                if _fileish_headers(headers, url):
                    network_urls.append(url)
                    network_meta.append({"url": url[:2000], "status": resp.status, "content_type": str(headers.get("content-type") or "")[:200], "content_disposition": str(headers.get("content-disposition") or "")[:300]})
            except Exception:
                pass

        page.on("response", on_response)
        for method, url in route_urls[:6]:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1800)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                body = page.locator("body").inner_text(timeout=15000)
                (out / "portal_page.txt").write_text(body[:1_500_000], encoding="utf-8")
                states.append(_page_state(body))

                anchors = page.locator("a[href]").evaluate_all("els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim()}))")
                dom_urls = []
                for item in anchors or []:
                    href = str((item or {}).get("href") or "").strip()
                    text = str((item or {}).get("text") or "").strip()
                    if href.startswith(("http://", "https://")) and FILE_URL_RE.search(f"{href} {text}") and not BLOCK_CONTROL_RE.search(text):
                        dom_urls.append(href)

                # Safe button pass. It can expand a public documents section or emit
                # a browser download. Authentication/registration/submission controls
                # are explicitly excluded.
                controls = page.locator("button, [role='button'], a")
                clicked = []
                for i in range(min(controls.count(), 120)):
                    if len(clicked) >= 10:
                        break
                    node = controls.nth(i)
                    try:
                        if not node.is_visible():
                            continue
                        text = re.sub(r"\s+", " ", node.inner_text(timeout=1000) or "").strip()
                        aria = str(node.get_attribute("aria-label") or "")
                        title = str(node.get_attribute("title") or "")
                        hay = f"{text} {aria} {title}".strip()
                        if not hay or not DOC_CONTROL_RE.search(hay) or BLOCK_CONTROL_RE.search(hay):
                            continue
                        try:
                            with page.expect_download(timeout=3500) as dl_info:
                                node.click(force=True, timeout=4000)
                            manifest["files"].append(base.persist_download(out, dl_info.value, page.url))
                            clicked.append({"text": hay[:250], "outcome": "DOWNLOADED"})
                        except Exception:
                            try:
                                node.click(force=True, timeout=2500)
                                page.wait_for_timeout(500)
                                clicked.append({"text": hay[:250], "outcome": "CLICKED_NO_DIRECT_DOWNLOAD"})
                            except Exception:
                                pass
                    except Exception:
                        continue

                urls = list(dict.fromkeys(dom_urls + network_urls))[:100]
                downloaded = 0
                for candidate_url in urls:
                    rec = base.direct_download(candidate_url, out, session)
                    if rec:
                        manifest["files"].append(rec)
                        downloaded += 1
                manifest["dce_method_attempts"].append({"method": f"V11_BROWSER_{method}", "url": url, "resolved_url": page.url, "dom_candidate_urls": dom_urls[:40], "network_files": network_meta[-80:], "safe_controls": clicked, "downloaded_after_discovery": downloaded})
                if manifest["files"]:
                    manifest["status"] = "DOWNLOADED_PUBLIC"
                    return
            except Exception as exc:
                manifest["dce_method_attempts"].append({"method": f"V11_BROWSER_{method}", "url": url, "outcome": "ERROR", "error": repr(exc)[:700]})
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

    for state in ("CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED", "AUTH_REQUIRED"):
        if state in states:
            manifest["status"] = state
            return
    manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"


# Register named downstream families plus the national lanes that v6 still sent
# through the old anchor-only cascade. Existing dedicated v10 routes remain intact.
V11_PUBLIC_PORTALS = set(EXACT_HOST_PORTALS.values()) | {p for _, p in SUFFIX_PORTALS} | {
    "GENERIC_PUBLIC_PAGE",
    "BELGIUM_PUBLIC", "SI_EJN", "SK_UVO", "HU_EKR", "RO_SEAP", "AT_OGD",
    "BG_AOP", "HR_EOJN", "SE_PUBLIC", "IS_RIKISKAUP",
}
for portal in sorted(V11_PUBLIC_PORTALS):
    if portal in {"SCOTLAND_PCS", "EE_RHR", "WORLD_BANK"}:
        continue
    base.ADAPTERS[portal] = adapter_public_spa_v11

# Keep batch/matrix contracts aware of direct national candidates that already carry
# one of the new route keys. This is additive and does not remove any v10 support.
matrix.BROWSER_PORTALS.update(V11_PUBLIC_PORTALS)
matrix.SUPPORTED.update(V11_PUBLIC_PORTALS)

# dce_worker_v2.run_ted resolves this symbol from its own module globals at runtime.
# Patching that reference preserves the mature TED transport while adding v11 routing.
v2.resolve_ted_candidate = resolve_ted_candidate_v11

if __name__ == "__main__":
    v2.main()
