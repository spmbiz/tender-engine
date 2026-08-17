from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v11 as v11
import dce_worker_v13 as v13

# High-frequency UK/NZ eSender families that appear downstream of Find a Tender,
# Contracts Finder and GETS. Naming them separately prevents a generic unresolved
# bucket from hiding a deterministic public-vs-registration access outcome.
EXACT_ESENDER_HOSTS = {
    "procontract.due-north.com": "UK_PROCONTRACT",
    "www.delta-esourcing.com": "UK_DELTA",
    "delta-esourcing.com": "UK_DELTA",
    "uk.eu-supply.com": "EU_SUPPLY_PUBLIC",
}
SUFFIX_ESENDER_HOSTS = (
    (".delta-esourcing.com", "UK_DELTA"),
    (".in-tendhost.co.uk", "UK_INTEND"),
    (".app.jaggaer.com", "UK_JAGGAER"),
    (".ukp.app.jaggaer.com", "UK_JAGGAER"),
    (".bravosolution.co.uk", "UK_JAGGAER"),
    (".tenderlink.com", "NZ_TENDERLINK"),
)

_old_portal_for_url = v13.portal_for_url_v13


def portal_for_url_v14(url: str) -> str | None:
    raw = str(url or "")
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").casefold()
        query = (parsed.query or "").casefold()
        path = (parsed.path or "").casefold()
    except Exception:
        return _old_portal_for_url(raw)
    if host in EXACT_ESENDER_HOSTS:
        return EXACT_ESENDER_HOSTS[host]
    for suffix, portal in SUFFIX_ESENDER_HOSTS:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return portal
    # Atamis public opportunity sites are Salesforce Experience/Sites domains.
    # Some tenants include "atamis" in the hostname; others expose the stable
    # ProSpend public landing page or SearchType=Projects route.
    if host.endswith((".my.salesforce-sites.com", ".my.site.com")):
        if "atamis" in host or "prospend__cs_publiclandingpage" in path or "searchtype=projects" in query:
            return "UK_ATAMIS"
    return _old_portal_for_url(raw)


v11.portal_for_url = portal_for_url_v14
v13.portal_for_url_v13 = portal_for_url_v14


def resolve_ted_candidate_v14(candidate: dict, timeout: int = 60) -> dict:
    result = v13.resolve_ted_candidate_v13(candidate, timeout=timeout)
    for item in result.get("downstream") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        portal = portal_for_url_v14(url)
        if portal:
            item["portal"] = portal
            route = item.get("route") if isinstance(item.get("route"), dict) else {}
            route.update({
                "detail_url": route.get("detail_url") or url,
                "downstream_host": (urlparse(url).hostname or "").casefold(),
                "portal_family_v14": portal,
            })
            item["route"] = route
    return result


v2.resolve_ted_candidate = resolve_ted_candidate_v14


def _saved_page_text(out: Path) -> str:
    parts = []
    for name in ("portal_page.txt", "portal_page_http.txt"):
        p = out / name
        try:
            if p.exists():
                parts.append(p.read_text(encoding="utf-8", errors="replace")[:1_500_000])
        except Exception:
            pass
    return "\n".join(parts)


PROCONTRACT_GATE_RE = re.compile(r"login.{0,80}register interest|register interest.{0,80}(?:login|log in)", re.I | re.S)
ATAMIS_INTEREST_RE = re.compile(
    r"register interest|documents?.{0,160}(?:only|visible).{0,80}(?:after|once).{0,80}register(?:ing|ed)? interest",
    re.I | re.S,
)
INTEND_AUTH_RE = re.compile(
    r"gain full access.{0,120}(?:register|login)|required to register.{0,120}(?:tender )?documents|"
    r"receive tender.{0,80}documentation.{0,180}(?:register|login)|tender documents posted.{0,120}required to register",
    re.I | re.S,
)
JAGGAER_AUTH_RE = re.compile(
    r"register and log on.{0,160}(?:download|tender documentation)|register.{0,160}gain access to tender documents|"
    r"secure access.{0,120}(?:tender|documentation)",
    re.I | re.S,
)
DELTA_AUTH_RE = re.compile(
    r"to express your interest.{0,120}(?:log-?in|login)|register.{0,180}(?:tender|response|itt)|"
    r"secure exchange of itt documents",
    re.I | re.S,
)
TENDERLINK_AUTH_RE = re.compile(
    r"access the rfx documents.{0,180}(?:registered|register).{0,80}tenderlink|"
    r"registered on tenderlink.{0,180}access the rfx documents",
    re.I | re.S,
)


def adapter_esender_v14(candidate: dict, out: Path, manifest: dict):
    v13.adapter_public_spa_v13(candidate, out, manifest)
    if manifest.get("files"):
        return
    portal = str(candidate.get("portal") or candidate.get("portal_key") or candidate.get("source") or "").upper()
    text = _saved_page_text(out)
    resolved_urls = [str((a or {}).get("resolved_url") or "") for a in manifest.get("dce_method_attempts") or []]
    resolved_blob = "\n".join(resolved_urls).casefold()

    if portal == "UK_PROCONTRACT" and (PROCONTRACT_GATE_RE.search(text) or "procontract.due-north.com/login" in resolved_blob):
        manifest["status"] = "INTEREST_RECORDING_REQUIRED"
        return
    if portal == "UK_ATAMIS" and ATAMIS_INTEREST_RE.search(text):
        manifest["status"] = "INTEREST_RECORDING_REQUIRED"
        return
    if portal == "UK_INTEND" and (INTEND_AUTH_RE.search(text) or "/aspx/login" in resolved_blob):
        manifest["status"] = "AUTH_REQUIRED"
        return
    if portal == "UK_JAGGAER" and (JAGGAER_AUTH_RE.search(text) or "/web/login" in resolved_blob):
        manifest["status"] = "AUTH_REQUIRED"
        return
    if portal == "UK_DELTA" and (DELTA_AUTH_RE.search(text) or "loginrespondtolist" in resolved_blob):
        manifest["status"] = "AUTH_REQUIRED"
        return
    if portal == "NZ_TENDERLINK" and TENDERLINK_AUTH_RE.search(text):
        manifest["status"] = "AUTH_REQUIRED"
        return


def adapter_canadabuys_v14(candidate: dict, out: Path, manifest: dict):
    """Deterministic anonymous CanadaBuys tender-document downloader.

    CanadaBuys publishes solicitation attachments under its own tender_notice file
    tree and explicitly states that these files are available without registration.
    We download only those first-party attachment URLs and preserve the normal
    public-page cascade as a fallback for source-system notices.
    """
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])
    route = candidate.get("route") or {}
    urls = []
    for u in (candidate.get("notice_url"), route.get("detail_url"), route.get("public_url"), route.get("source_url")):
        if isinstance(u, str) and "canadabuys.canada.ca/" in u and u not in urls:
            urls.append(u)
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/14.0 public procurement research"})
    for url in urls[:5]:
        try:
            r = session.get(url, timeout=45, allow_redirects=True)
            raw = html.unescape(r.text if r.ok else "")
            file_urls = []
            for href in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
                absolute = urljoin(r.url, html.unescape(href))
                parsed = urlparse(absolute)
                if (parsed.hostname or "").casefold() != "canadabuys.canada.ca":
                    continue
                if "/sites/default/files/webform/tender_notice/" not in parsed.path.casefold():
                    continue
                if absolute not in file_urls:
                    file_urls.append(absolute)
            downloaded = 0
            for file_url in file_urls[:100]:
                rec = base.direct_download(file_url, out, session)
                if rec:
                    manifest["files"].append(rec)
                    downloaded += 1
            manifest["dce_method_attempts"].append({
                "method": "CANADABUYS_FIRST_PARTY_ATTACHMENTS_V14",
                "url": url,
                "resolved_url": r.url,
                "http_status": r.status_code,
                "attachment_urls": file_urls[:100],
                "downloaded": downloaded,
            })
            if downloaded:
                manifest["status"] = "DOWNLOADED_PUBLIC"
                return
        except Exception as exc:
            manifest["dce_method_attempts"].append({
                "method": "CANADABUYS_FIRST_PARTY_ATTACHMENTS_V14",
                "url": url,
                "outcome": "ERROR",
                "error": repr(exc)[:700],
            })
    v13.adapter_public_spa_v13(candidate, out, manifest)


def adapter_nz_gets_v14(candidate: dict, out: Path, manifest: dict):
    v13.adapter_public_spa_v13(candidate, out, manifest)
    if manifest.get("files"):
        return
    text = _saved_page_text(out)
    if TENDERLINK_AUTH_RE.search(text):
        manifest["status"] = "AUTH_REQUIRED"
        route = manifest.setdefault("resolved_route", {})
        links = re.findall(r"https?://(?:www\.)?tenderlink\.com/[^\s<>\"']*", text, re.I)
        if links:
            route["downstream_tenderlink"] = links[0].rstrip(".,);]")


EXTRA_PUBLIC_ESENDERS = {"UK_PROCONTRACT", "UK_ATAMIS", "UK_DELTA", "UK_INTEND", "UK_JAGGAER", "NZ_TENDERLINK"}
for portal in EXTRA_PUBLIC_ESENDERS:
    base.ADAPTERS[portal] = adapter_esender_v14
v11.V11_PUBLIC_PORTALS.update(EXTRA_PUBLIC_ESENDERS)
v11.matrix.BROWSER_PORTALS.update(EXTRA_PUBLIC_ESENDERS)
v11.matrix.SUPPORTED.update(EXTRA_PUBLIC_ESENDERS)

# Strengthen two existing national lanes rather than adding parallel portal keys.
base.ADAPTERS["CA_CANADABUYS"] = adapter_canadabuys_v14
base.ADAPTERS["NZ_GETS"] = adapter_nz_gets_v14

if __name__ == "__main__":
    v2.main()
