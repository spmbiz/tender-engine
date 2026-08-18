from __future__ import annotations

import copy
import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v13 as v13
import dce_worker_v21 as v21  # registers the complete validated V21 stack


# BOAMP is an official publication/notice source. The consultation documents are
# commonly hosted on the buyer profile named in the Communication section. V22
# therefore treats BOAMP as a router and never promotes the BOAMP notice PDF itself
# as DCE evidence.
FR_HOST_EXACT = {
    "marches-publics.gouv.fr": "FR_PLACE",
    "www.marches-publics.gouv.fr": "FR_PLACE",
    "www.marches-publics.info": "FR_AWS",
    "marches-publics.info": "FR_AWS",
    "www.marches-securises.fr": "FR_MARCHES_SECUR",
    "marches-securises.fr": "FR_MARCHES_SECUR",
    "maximilien.fr": "FR_MAXIMILIEN",
    "www.maximilien.fr": "FR_MAXIMILIEN",
}
FR_HOST_SUFFIX = (
    (".achatpublic.com", "FR_ACHATPUBLIC"),
    (".e-marchespublics.com", "FR_E_MARCHESPUBLICS"),
    (".marches-publics.info", "FR_AWS"),
    (".aws-achat.info", "FR_AWS"),
    (".marches-securises.fr", "FR_MARCHES_SECUR"),
    (".maximilien.fr", "FR_MAXIMILIEN"),
)
PROFILE_SIGNAL_RE = re.compile(
    r"profil\s+d['’]acheteur|documents?\s+de\s+la\s+consultation|"
    r"acc[eè]s\s+aux\s+documents?|dossier\s+de\s+consultation|\bDCE\b|"
    r"plateforme\s+de\s+d[eé]mat[eé]rialisation|adresse\s+internet\s+du\s+profil",
    re.I,
)
BOAMP_HOST_RE = re.compile(r"(?:^|\.)boamp\.fr$", re.I)


def portal_for_fr_url_v22(url: str) -> str | None:
    try:
        host = (urlparse(str(url or "")).hostname or "").casefold()
    except Exception:
        return None
    if host in FR_HOST_EXACT:
        return FR_HOST_EXACT[host]
    for suffix, portal in FR_HOST_SUFFIX:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return portal
    try:
        return v13.portal_for_url_v13(url)
    except Exception:
        return None


def _candidate_urls(candidate: dict) -> list[str]:
    out: list[str] = []
    def add(value):
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in out:
            out.append(value)
    add(candidate.get("notice_url"))
    route = candidate.get("route") or {}
    if isinstance(route, dict):
        for value in route.values():
            if isinstance(value, str):
                add(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        add(item)
                    elif isinstance(item, dict):
                        add(item.get("url"))
    for doc in candidate.get("documents") or []:
        if isinstance(doc, str): add(doc)
        elif isinstance(doc, dict): add(doc.get("url"))
    for u in re.findall(r"https?://[^\s<>\"']+", str(candidate.get("description") or ""))[:30]:
        add(html.unescape(u).rstrip(".,);]"))
    return out


def extract_boamp_downstream_links(raw: str, base_url: str = "") -> list[dict]:
    """Rank buyer-profile / consultation URLs without treating buyer homepages as DCE."""
    text = html.unescape(str(raw or ""))
    candidates: dict[str, dict] = {}

    # BOAMP labels precede their link. Keep the window mostly backward-looking so
    # the next field's "profil d'acheteur" label cannot contaminate the previous
    # ordinary buyer-homepage link.
    for m in re.finditer(r"href\s*=\s*[\"']([^\"']+)[\"']", text, re.I):
        href = html.unescape(m.group(1)).strip()
        url = urljoin(base_url, href)
        if not url.startswith(("http://", "https://")):
            continue
        lo, hi = max(0, m.start() - 240), min(len(text), m.end() + 20)
        context = re.sub(r"<[^>]+>", " ", text[lo:hi])
        context = re.sub(r"\s+", " ", context).strip()
        candidates.setdefault(url, {"url": url, "contexts": []})["contexts"].append(context)

    # Structured descriptions sometimes carry the profile URL as plain text. The
    # same backward-biased window binds the nearby label to this URL only.
    for m in re.finditer(r"https?://[^\s<>\"']+", text, re.I):
        url = html.unescape(m.group(0)).rstrip(".,);]")
        lo, hi = max(0, m.start() - 220), min(len(text), m.end() + 30)
        context = re.sub(r"<[^>]+>", " ", text[lo:hi])
        context = re.sub(r"\s+", " ", context).strip()
        candidates.setdefault(url, {"url": url, "contexts": []})["contexts"].append(context)

    ranked = []
    for url, item in candidates.items():
        try:
            host = (urlparse(url).hostname or "").casefold()
        except Exception:
            continue
        if not host or BOAMP_HOST_RE.search(host) or host.endswith("ted.europa.eu"):
            continue
        portal = portal_for_fr_url_v22(url)
        context = " ".join(item.get("contexts") or [])[:1800]
        signal = bool(PROFILE_SIGNAL_RE.search(context))
        # Known procurement portals are acceptable when BOAMP publishes them even if
        # HTML label context was lost during normalization. Unknown hosts require an
        # explicit buyer-profile/document signal.
        if not portal and not signal:
            continue
        score = (8 if signal else 0) + (6 if portal and portal.startswith("FR_") else 2 if portal else 0)
        path = (urlparse(url).path or "").casefold()
        if any(token in path for token in ("consult", "entreprise", "march", "tender", "procedure")):
            score += 2
        ranked.append({"url": url, "portal": portal or "GENERIC_PUBLIC_PAGE", "score": score, "context": context[:500]})
    ranked.sort(key=lambda x: (-int(x["score"]), x["url"]))
    return ranked


def _merge_child(manifest: dict, child: dict, method: str, url: str, portal: str) -> None:
    manifest.setdefault("dce_method_attempts", []).append({
        "method": method, "url": url, "portal": portal,
        "outcome": child.get("status"), "files": len(child.get("files") or []),
    })
    manifest.setdefault("dce_method_attempts", []).extend(child.get("dce_method_attempts") or [])
    for rec in child.get("files") or []:
        manifest.setdefault("files", []).append(rec)


def adapter_fr_boamp_v22(candidate: dict, out: Path, manifest: dict):
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/22.0 public procurement research"})

    evidence_blobs: list[tuple[str, str]] = []
    desc = str(candidate.get("description") or "")
    if desc:
        evidence_blobs.append((desc, str(candidate.get("notice_url") or "")))

    boamp_urls = []
    for url in _candidate_urls(candidate):
        try:
            host = (urlparse(url).hostname or "").casefold()
        except Exception:
            host = ""
        if BOAMP_HOST_RE.search(host) and url not in boamp_urls:
            boamp_urls.append(url)
        elif host and not BOAMP_HOST_RE.search(host) and portal_for_fr_url_v22(url):
            # Only known procurement hosts may be promoted without nearby BOAMP
            # profile/document label context. Unknown buyer homepages remain ignored.
            evidence_blobs.append((f"Adresse internet du profil d'acheteur: {url}", url))

    for url in boamp_urls[:3]:
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            manifest["dce_method_attempts"].append({
                "method": "FR_BOAMP_NOTICE_ROUTE_DISCOVERY_V22", "url": url,
                "resolved_url": r.url, "http_status": r.status_code, "bytes": len(r.content),
            })
            if r.ok:
                evidence_blobs.append((r.text, r.url))
                try:
                    (out / "portal_page_boamp.txt").write_text(
                        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(r.text)))[:1_000_000],
                        encoding="utf-8",
                    )
                except Exception:
                    pass
        except Exception as exc:
            manifest["dce_method_attempts"].append({
                "method": "FR_BOAMP_NOTICE_ROUTE_DISCOVERY_V22", "url": url,
                "outcome": "ERROR", "error": repr(exc)[:500],
            })

    ranked: list[dict] = []
    seen = set()
    for blob, base_url in evidence_blobs:
        for item in extract_boamp_downstream_links(blob, base_url):
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            ranked.append(item)
    ranked.sort(key=lambda x: (-int(x["score"]), x["url"]))
    manifest["fr_boamp_downstream_candidates_v22"] = ranked[:20]

    child_statuses = []
    for item in ranked[:3]:
        url = item["url"]
        portal = item["portal"]
        trial = copy.deepcopy(candidate)
        trial["portal"] = portal
        trial["notice_url"] = url
        route = dict(trial.get("route") or {})
        route.update({"detail_url": url, "documents_url": url, "boamp_downstream_v22": True})
        trial["route"] = route
        child = {"files": [], "dce_method_attempts": []}
        adapter = base.ADAPTERS.get(portal)
        if portal == "GENERIC_PUBLIC_PAGE" or adapter is None or adapter is adapter_fr_boamp_v22:
            adapter = v13.adapter_public_spa_v13
        try:
            adapter(trial, out, child)
        except Exception as exc:
            child["status"] = "ERROR_RETRYABLE"
            child["error"] = repr(exc)[:700]
        _merge_child(manifest, child, "FR_BOAMP_DOWNSTREAM_DISPATCH_V22", url, portal)
        child_statuses.append(str(child.get("status") or "UNKNOWN").upper())
        if child.get("files"):
            manifest["status"] = "DOWNLOADED_PUBLIC"
            return
        if child.get("status") in {"AUTH_REQUIRED", "CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED", "REGISTRATION_REQUIRED"}:
            manifest["status"] = child["status"]
            return

    for status in ("CAPTCHA_REQUIRED", "AUTH_REQUIRED", "INTEREST_RECORDING_REQUIRED", "ERROR_RETRYABLE", "ROUTE_INCOMPLETE"):
        if status in child_statuses:
            manifest["status"] = status
            return
    # No downstream route is better represented as unresolved than as a false BOAMP
    # notice download. The tender remains eligible for alternative route discovery.
    manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"


base.ADAPTERS["FR_BOAMP"] = adapter_fr_boamp_v22


if __name__ == "__main__":
    v21.v20.install_http_probe_guard()
    v21.v2.main()
