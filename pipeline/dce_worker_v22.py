from __future__ import annotations

import copy
import html
import json
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
BOAMP_API_URL = "https://www.boamp.fr/api/explore/v2.1/catalog/datasets/boamp/records"
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
    r"profil[_\s-]*d?[’'_]?acheteur|profil\s+d['’]acheteur|"
    r"documents?[_\s-]*(?:de[_\s-]*)?la[_\s-]*consultation|"
    r"acc[eè]s[_\s-]*aux[_\s-]*documents?|dossier[_\s-]*de[_\s-]*consultation|\bDCE\b|"
    r"plateforme[_\s-]*de[_\s-]*d[eé]mat[eé]rialisation|adresse[_\s-]*internet[_\s-]*du[_\s-]*profil|"
    r"url[_\s-]*(?:profil|dce|documents?|consultation)",
    re.I,
)
BOAMP_HOST_RE = re.compile(r"(?:^|\.)boamp\.fr$", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"'\\]+", re.I)
IDWEB_RE = re.compile(r"(?:FR-BOAMP:|idweb[:=\"'%20]+)(\d{2}-\d+)", re.I)


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
        if isinstance(doc, str):
            add(doc)
        elif isinstance(doc, dict):
            add(doc.get("url"))
    for u in URL_RE.findall(str(candidate.get("description") or ""))[:30]:
        add(html.unescape(u).rstrip(".,);]"))
    return out


def _candidate_idweb(candidate: dict) -> str | None:
    for raw in (candidate.get("candidate_id"), candidate.get("notice_url"), *(_candidate_urls(candidate)[:8])):
        m = IDWEB_RE.search(str(raw or ""))
        if m:
            return m.group(1)
    return None


def _structured_strings(value, path: tuple[str, ...] = (), depth: int = 0):
    """Yield path/value pairs from BOAMP's nested `donnees`/`gestion` JSON."""
    if depth > 16:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _structured_strings(item, path + (str(key),), depth + 1)
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            yield from _structured_strings(item, path + (str(i),), depth + 1)
        return
    if not isinstance(value, str):
        return
    text = html.unescape(value).strip()
    if not text:
        return
    # Opendatasoft exposes some BOAMP fields as JSON-encoded strings.
    if text[:1] in "[{" and len(text) <= 8_000_000:
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from _structured_strings(parsed, path, depth + 1)
            return
    yield (" / ".join(path), text)


def _rank_url(url: str, context: str) -> dict | None:
    url = html.unescape(str(url or "")).rstrip(".,);]")
    if not url.startswith(("http://", "https://")):
        return None
    try:
        host = (urlparse(url).hostname or "").casefold()
    except Exception:
        return None
    if not host or BOAMP_HOST_RE.search(host) or host.endswith("ted.europa.eu"):
        return None
    portal = portal_for_fr_url_v22(url)
    signal = bool(PROFILE_SIGNAL_RE.search(context or ""))
    if not portal and not signal:
        return None
    score = (10 if signal else 0) + (7 if portal and portal.startswith("FR_") else 2 if portal else 0)
    path = (urlparse(url).path or "").casefold()
    if any(token in path for token in ("consult", "entreprise", "march", "tender", "procedure", "dce")):
        score += 2
    return {"url": url, "portal": portal or "GENERIC_PUBLIC_PAGE", "score": score, "context": (context or "")[:800]}


def extract_boamp_structured_links(record: dict) -> list[dict]:
    """Extract profile/DCE routes from one exact official BOAMP Open Data record."""
    ranked: dict[str, dict] = {}
    for key in ("donnees", "gestion", "DONNEES", "GESTION"):
        value = record.get(key)
        if value is None:
            continue
        for path, text in _structured_strings(value):
            context = f"{path}: {text[:1200]}"
            for url in URL_RE.findall(text):
                item = _rank_url(url, context)
                if item and (url not in ranked or item["score"] > ranked[url]["score"]):
                    ranked[url] = item
    # Some schemas expose direct fields outside `donnees`.
    for path, text in _structured_strings(record):
        if not PROFILE_SIGNAL_RE.search(path):
            continue
        context = f"{path}: {text[:1200]}"
        for url in URL_RE.findall(text):
            item = _rank_url(url, context)
            if item and (url not in ranked or item["score"] > ranked[url]["score"]):
                ranked[url] = item
    return sorted(ranked.values(), key=lambda x: (-int(x["score"]), x["url"]))


def _boamp_api_record(session: requests.Session, idweb: str, manifest: dict) -> dict | None:
    try:
        response = session.get(
            BOAMP_API_URL,
            params={"select": "*", "where": f'idweb="{idweb}"', "limit": 1},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") or [] if isinstance(payload, dict) else []
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "FR_BOAMP_OFFICIAL_OD_API_V22",
            "url": response.url,
            "http_status": response.status_code,
            "idweb": idweb,
            "records": len(rows),
        })
        if rows and isinstance(rows[0], dict):
            return rows[0]
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "FR_BOAMP_OFFICIAL_OD_API_V22",
            "idweb": idweb,
            "outcome": "ERROR",
            "error": repr(exc)[:700],
        })
    return None


def extract_boamp_downstream_links(raw: str, base_url: str = "") -> list[dict]:
    """Rank buyer-profile / consultation URLs in BOAMP HTML/text fail-closed."""
    text = html.unescape(str(raw or ""))
    candidates: dict[str, dict] = {}

    # BOAMP labels precede their link. Keep the window mostly backward-looking so
    # the next field's buyer-profile label cannot contaminate the previous homepage.
    for m in re.finditer(r"href\s*=\s*[\"']([^\"']+)[\"']", text, re.I):
        href = html.unescape(m.group(1)).strip()
        url = urljoin(base_url, href)
        if not url.startswith(("http://", "https://")):
            continue
        lo, hi = max(0, m.start() - 240), min(len(text), m.end() + 20)
        context = re.sub(r"<[^>]+>", " ", text[lo:hi])
        context = re.sub(r"\s+", " ", context).strip()
        candidates.setdefault(url, {"url": url, "contexts": []})["contexts"].append(context)

    for m in URL_RE.finditer(text):
        url = html.unescape(m.group(0)).rstrip(".,);]")
        lo, hi = max(0, m.start() - 220), min(len(text), m.end() + 30)
        context = re.sub(r"<[^>]+>", " ", text[lo:hi])
        context = re.sub(r"\s+", " ", context).strip()
        candidates.setdefault(url, {"url": url, "contexts": []})["contexts"].append(context)

    ranked = []
    for url, item in candidates.items():
        context = " ".join(item.get("contexts") or [])[:1800]
        found = _rank_url(url, context)
        if found:
            ranked.append(found)
    ranked.sort(key=lambda x: (-int(x["score"]), x["url"]))
    return ranked


def _merge_child(manifest: dict, child: dict, method: str, url: str, portal: str) -> None:
    manifest.setdefault("dce_method_attempts", []).append({
        "method": method,
        "url": url,
        "portal": portal,
        "outcome": child.get("status"),
        "files": len(child.get("files") or []),
    })
    manifest.setdefault("dce_method_attempts", []).extend(child.get("dce_method_attempts") or [])
    for rec in child.get("files") or []:
        manifest.setdefault("files", []).append(rec)


def adapter_fr_boamp_v22(candidate: dict, out: Path, manifest: dict):
    manifest.setdefault("files", [])
    manifest.setdefault("dce_method_attempts", [])
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/22.0 public procurement research"})

    ranked: list[dict] = []
    seen = set()

    # Deterministic first lane: exact BOAMP Open Data record by idweb. The BOAMP
    # website page itself is a search SPA shell and is not authoritative DCE content.
    idweb = _candidate_idweb(candidate)
    manifest["fr_boamp_idweb_v22"] = idweb
    if idweb:
        record = _boamp_api_record(session, idweb, manifest)
        if record:
            manifest["fr_boamp_api_record_found_v22"] = True
            try:
                (out / "boamp_record_v22.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)[:8_000_000], encoding="utf-8")
            except Exception:
                pass
            for item in extract_boamp_structured_links(record):
                if item["url"] not in seen:
                    seen.add(item["url"])
                    ranked.append(item)

    # Preserve already-materialized external procurement URLs and description text.
    evidence_blobs: list[tuple[str, str]] = []
    desc = str(candidate.get("description") or "")
    if desc:
        evidence_blobs.append((desc, str(candidate.get("notice_url") or "")))
    for url in _candidate_urls(candidate):
        try:
            host = (urlparse(url).hostname or "").casefold()
        except Exception:
            host = ""
        if host and not BOAMP_HOST_RE.search(host) and portal_for_fr_url_v22(url):
            evidence_blobs.append((f"Adresse internet du profil d'acheteur: {url}", url))
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
