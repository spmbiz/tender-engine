from __future__ import annotations

import copy
import html
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v11 as v11
import dce_worker_v15 as v15
import dce_worker_v21 as v21  # register the complete validated V21 stack first
import placsp_atom


# V22 is deliberately additive. It does not replace the V21 resolver stack; it
# hardens generic transport success, recovers two high-value generic BT-15 routes,
# and improves exact PLACSP matching for TED-sourced candidates.

DOC_EXT_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z|rar|rtf|xml|odt|ods)(?:$|[?#])", re.I)
FONT_EXT_RE = re.compile(r"\.(?:ttf|otf|woff2?|eot)(?:$|[?#])", re.I)
IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|svg)(?:$|[?#])", re.I)
STATIC_PATH_RE = re.compile(r"/(?:assets?|static|fonts?|icons?|images?|img|public-resources)/", re.I)
PROCUREMENT_HINT_RE = re.compile(
    r"tender|procurement|document|dossier|dce|annex|appendix|attachment|specification|"
    r"terms[-_ ]of[-_ ]reference|\btor\b|\bswz\b|pliego|cahier|ccap|cctp|rc[-_ .]|"
    r"vergabe|unterlag|leistung|lot|contract|offre|prilo|z[aá]kaz",
    re.I,
)
OBVIOUS_PORTAL_ASSET_RE = re.compile(
    r"(?:^|[/_. -])ionicons(?:[_. -]|$)|"
    r"(?:^|[/_. -])favicon(?:[_. -]|$)|"
    r"rib[-_ ]tender[-_ ]nutzungsbedingungen|"
    r"(?:^|[/_. -])(?:en[-_ ])?agb[-_ ]?subreport|"
    r"datenschutzerklaerung[-_ ]?subreport|"
    r"vereinbarung[-_ ]?auftragsdatenverarbeitung[-_ ]?subreport|"
    r"(?:^|[/_. -])depot[-_ ]?pli\.pdf(?:$|[?#])|"
    r"terms[-_ ]?(?:of[-_ ]?)?use|privacy[-_ ]?policy|"
    r"user[-_ ]?guide|supplier[-_ ]?guide|portal[-_ ]?guide",
    re.I,
)
LOGIN_ROUTE_RE = re.compile(r"/(?:login(?:\.aspx)?|signin|sign-in|auth(?:/|$)|oauth/authorize)(?:[/?#]|$)", re.I)
NEN_PROFILE_RE = re.compile(r"/(?:profil|profily-zadavatelu-platne/detail-profilu)/([^/?#]+)", re.I)
NEN_DETAIL_HREF_RE = re.compile(r"/verejne-zakazky/detail-zakazky/(N\d{3}-\d{2}-V\d{6,12})", re.I)
PLACE_DETAIL_RE = re.compile(r"/app\.php/entreprise/consultation/(\d+)", re.I)

_ORIGINAL_LOOKS_LIKE_FILE = base.looks_like_file
_ORIGINAL_FILEISH_HEADERS = v11._fileish_headers
_ORIGINAL_ENTRY_MATCH = v15._entry_match
_OLD_PLACE_ADAPTER = base.ADAPTERS.get("FR_PLACE", base.adapter_place)


def _scalar(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("eng", "en", "fra", "fr", "value"):
            if key in value:
                got = _scalar(value.get(key))
                if got:
                    return got
        for item in value.values():
            got = _scalar(item)
            if got:
                return got
        return ""
    if isinstance(value, list):
        for item in value:
            got = _scalar(item)
            if got:
                return got
        return ""
    return str(value)


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _candidate_title(candidate: dict) -> str:
    return _scalar(candidate.get("title") or candidate.get("notice-title") or candidate.get("notice_title"))


def _candidate_buyer(candidate: dict) -> str:
    return _scalar(candidate.get("buyer") or candidate.get("buyer-name") or candidate.get("buyer_name"))


def _distinctive_tokens(value: str) -> list[str]:
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "public", "service", "services",
        "supply", "supplies", "contract", "tender", "procurement", "notice", "framework", "project",
        "de", "des", "du", "la", "le", "les", "et", "pour", "dans", "sur", "une", "un",
    }
    return sorted({tok for tok in _fold(value).split() if len(tok) >= 4 and tok not in stop})


def _response_filename(resp: requests.Response) -> str:
    cd = str(resp.headers.get("content-disposition") or "")
    m = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", cd, re.I)
    if m:
        return html.unescape(m.group(1)).strip().strip('"')
    return Path(urlparse(str(resp.url or "")).path).name


def _obvious_non_dce_name_or_url(name: str, url: str, content_type: str = "") -> tuple[bool, str]:
    hay = f"{name} {url}".strip()
    low_ct = str(content_type or "").casefold()
    if OBVIOUS_PORTAL_ASSET_RE.search(hay):
        return True, "KNOWN_PORTAL_BOILERPLATE_OR_STATIC_ASSET"
    if FONT_EXT_RE.search(name) or FONT_EXT_RE.search(url) or low_ct.startswith("font/"):
        return True, "FONT_ASSET"
    if IMAGE_EXT_RE.search(name) or IMAGE_EXT_RE.search(url):
        # Images can be legitimate tender attachments. Reject only obvious web/static
        # resources that carry no procurement-document signal.
        if STATIC_PATH_RE.search(url) and not PROCUREMENT_HINT_RE.search(hay):
            return True, "STATIC_IMAGE_ASSET"
    return False, ""


def _magic_is_document(body: bytes) -> bool:
    prefix = bytes((body or b"")[:16])
    return bool(
        prefix.startswith(b"%PDF-")
        or prefix.startswith(b"PK\x03\x04")
        or prefix.startswith(b"\xd0\xcf\x11\xe0")
        or prefix.startswith(b"7z\xbc\xaf\x27\x1c")
        or prefix.startswith(b"Rar!\x1a\x07")
        or prefix.startswith(b"{\\rtf")
    )


def looks_like_file_v22(resp: requests.Response) -> bool:
    name = _response_filename(resp)
    url = str(resp.url or "")
    ct = str(resp.headers.get("content-type") or "")
    cd = str(resp.headers.get("content-disposition") or "")
    blocked, _ = _obvious_non_dce_name_or_url(name, url, ct)
    if blocked:
        return False

    low_ct = ct.casefold()
    if "text/html" in low_ct:
        return False
    if DOC_EXT_RE.search(name) or DOC_EXT_RE.search(url):
        return True
    if "attachment" in cd.casefold():
        return not (FONT_EXT_RE.search(name) or FONT_EXT_RE.search(url))
    if any(x in low_ct for x in (
        "application/pdf", "application/zip", "application/x-zip", "application/msword",
        "application/vnd.openxmlformats", "application/vnd.ms-", "text/csv", "application/rtf",
    )):
        return True
    if "application/octet-stream" in low_ct:
        return _magic_is_document(resp.content or b"")
    return _ORIGINAL_LOOKS_LIKE_FILE(resp)


def _record_transport_rejection(out: Path, url: str, reason: str, name: str = "", content_type: str = "") -> None:
    try:
        path = out.parent / "transport_rejections.jsonl"
        row = {"url": url, "name": name, "content_type": content_type, "reason": reason}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def direct_download_v22(url: str, out: Path, session: requests.Session) -> dict | None:
    pre_name = Path(urlparse(str(url or "")).path).name
    blocked, reason = _obvious_non_dce_name_or_url(pre_name, str(url or ""))
    if blocked:
        _record_transport_rejection(out, str(url or ""), reason, pre_name)
        return None
    try:
        r = session.get(url, timeout=45, allow_redirects=True)
        name = _response_filename(r)
        ct = str(r.headers.get("content-type") or "")
        blocked, reason = _obvious_non_dce_name_or_url(name, str(r.url or url), ct)
        if blocked:
            _record_transport_rejection(out, str(r.url or url), reason, name, ct)
            return None
        if r.ok and r.content and looks_like_file_v22(r):
            return base.persist_bytes(out, base.filename_from_response(r, "download.bin"), r.content, r.url, ct)
    except Exception:
        return None
    return None


def _fileish_headers_v22(headers: dict, url: str = "") -> bool:
    name = Path(urlparse(str(url or "")).path).name
    ct = str((headers or {}).get("content-type") or "")
    blocked, _ = _obvious_non_dce_name_or_url(name, str(url or ""), ct)
    if blocked:
        return False
    return _ORIGINAL_FILEISH_HEADERS(headers, url)


def _sanitize_manifest_files(manifest: dict) -> int:
    kept = []
    rejected = []
    for rec in manifest.get("files") or []:
        if not isinstance(rec, dict):
            continue
        blocked, reason = _obvious_non_dce_name_or_url(
            str(rec.get("name") or ""),
            str(rec.get("source_url") or ""),
            str(rec.get("content_type") or ""),
        )
        if blocked:
            rejected.append({**rec, "transport_rejection_reason": reason})
        else:
            kept.append(rec)
    if not rejected:
        return 0
    manifest["files"] = kept
    manifest.setdefault("transport_rejected_files", []).extend(rejected)
    manifest["transport_hygiene_v22"] = {
        "rejected": len(rejected),
        "kept": len(kept),
        "rule": "Obvious portal boilerplate/static assets are preserved as telemetry but cannot satisfy DCE transport success.",
    }
    if not kept and str(manifest.get("status") or "") == "DOWNLOADED_PUBLIC":
        manifest["transport_status_before_hygiene_v22"] = "DOWNLOADED_PUBLIC"
        manifest["status"] = "GENERIC_PUBLIC_PAGE_UNRESOLVED"
    return len(rejected)


def _refine_auth_from_redirect(manifest: dict) -> bool:
    if manifest.get("files"):
        return False
    current = str(manifest.get("status") or "")
    if current not in {"GENERIC_PUBLIC_PAGE_UNRESOLVED", "NO_PUBLIC_FILE", "PUBLIC_POSTBACK_NO_DOWNLOAD"}:
        return False
    for attempt in manifest.get("dce_method_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        resolved = str(attempt.get("resolved_url") or "")
        if resolved and LOGIN_ROUTE_RE.search(urlparse(resolved).path):
            manifest["status"] = "AUTH_REQUIRED"
            manifest["auth_redirect_v22"] = resolved
            return True
    return False


def _rethrow_http_probe_boundary(exc: Exception) -> None:
    if exc.__class__.__name__ == "HttpProbeBrowserBoundary" or "DCE_HTTP_PROBE_ONLY_BROWSER_BOUNDARY" in str(exc):
        raise exc


def _link_rows(page, href_pattern: re.Pattern) -> list[dict]:
    anchors = page.locator("a[href]")
    try:
        rows = anchors.evaluate_all(
            """els => els.map(a => { const p=a.closest('tr,li,article,section,[role=row],.row,.card,.list-group-item') || a.parentElement; return {href:a.href||'', text:((p&&p.innerText)||a.innerText||a.textContent||'').trim()}; })"""
        )
    except Exception:
        return []
    out = []
    seen = set()
    for row in rows or []:
        href = str((row or {}).get("href") or "")
        if not href_pattern.search(href) or href in seen:
            continue
        seen.add(href)
        out.append({"href": href, "text": str((row or {}).get("text") or "")[:4000]})
    return out


def _pick_best_link(rows: list[dict], candidate: dict) -> tuple[str | None, list[dict]]:
    title = _candidate_title(candidate)
    title_fold = _fold(title)
    tokens = _distinctive_tokens(title)
    buyer_tokens = _distinctive_tokens(_candidate_buyer(candidate))
    scored = []
    for row in rows:
        text = _fold(row.get("text") or "")
        hits = [t for t in tokens if re.search(rf"\b{re.escape(t)}\b", text)]
        buyer_hits = [t for t in buyer_tokens if re.search(rf"\b{re.escape(t)}\b", text)]
        phrase = bool(title_fold and len(title_fold) >= 12 and title_fold in text)
        ratio = len(hits) / len(tokens) if tokens else 0.0
        score = (100 if phrase else 0) + len(hits) * 10 + len(buyer_hits) * 3 + int(ratio * 10)
        scored.append({**row, "score": score, "title_hits": hits[:20], "buyer_hits": buyer_hits[:10], "title_ratio": round(ratio, 4), "title_phrase": phrase})
    scored.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("href") or "")))
    if not scored:
        return None, []
    if len(scored) == 1 and (not tokens or scored[0]["title_phrase"] or scored[0]["title_ratio"] >= 0.35):
        return scored[0]["href"], scored
    top = scored[0]
    second_score = int(scored[1].get("score") or 0) if len(scored) > 1 else -1
    strong = bool(top.get("title_phrase") or (len(top.get("title_hits") or []) >= 2 and float(top.get("title_ratio") or 0) >= 0.35))
    if strong and int(top.get("score") or 0) > second_score:
        return str(top.get("href") or ""), scored
    return None, scored


def _nen_profile_url(candidate: dict) -> str:
    route = candidate.get("route") or {}
    for value in (
        route.get("detail_url") if isinstance(route, dict) else None,
        route.get("public_url") if isinstance(route, dict) else None,
        candidate.get("notice_url"),
    ):
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            continue
        parsed = urlparse(value)
        if (parsed.hostname or "").casefold() == "nen.nipez.cz" and NEN_PROFILE_RE.search(parsed.path):
            return value
    return ""


def _recover_nen_detail(candidate: dict, manifest: dict) -> str | None:
    profile = _nen_profile_url(candidate)
    if not profile:
        return None
    pw = browser = context = page = None
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(profile, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1200)
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        rows = _link_rows(page, NEN_DETAIL_HREF_RE)
        chosen, scored = _pick_best_link(rows, candidate)
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "CZ_NEN_PROFILE_ROUTE_RECOVERY_V22",
            "url": profile,
            "resolved_url": page.url,
            "candidate_links": scored[:20],
            "outcome": "MATCHED" if chosen else "NO_UNAMBIGUOUS_MATCH",
        })
        return chosen
    except Exception as exc:
        _rethrow_http_probe_boundary(exc)
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "CZ_NEN_PROFILE_ROUTE_RECOVERY_V22", "url": profile,
            "outcome": "ERROR", "error": repr(exc)[:700],
        })
        return None
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


def adapter_nen_v22(candidate: dict, out: Path, manifest: dict):
    if v21.nen_documents_url(candidate):
        v21.adapter_cz_nen_v21(candidate, out, manifest)
        _sanitize_manifest_files(manifest)
        _refine_auth_from_redirect(manifest)
        return
    detail = _recover_nen_detail(candidate, manifest)
    if detail:
        trial = copy.deepcopy(candidate)
        route = dict(trial.get("route") or {})
        route["detail_url"] = detail
        route["nen_profile_recovered_detail_v22"] = detail
        trial["route"] = route
        trial["notice_url"] = detail
        manifest["cz_nen_profile_recovered_detail_v22"] = detail
        v21.adapter_cz_nen_v21(trial, out, manifest)
    else:
        v21.adapter_cz_nen_v21(candidate, out, manifest)
    _sanitize_manifest_files(manifest)
    _refine_auth_from_redirect(manifest)


def _place_specific_route(candidate: dict) -> dict | None:
    route = candidate.get("route") or {}
    consultation = str(route.get("consultation_id") or candidate.get("consultation_id") or "").strip()
    org = str(route.get("org_acronym") or candidate.get("org_acronym") or "").strip()
    urls = []
    for value in (
        route.get("documents_url") if isinstance(route, dict) else None,
        route.get("detail_url") if isinstance(route, dict) else None,
        candidate.get("notice_url"),
    ):
        if isinstance(value, str) and "marches-publics.gouv.fr" in value.casefold():
            urls.append(value)
    if not consultation:
        for url in urls:
            m = PLACE_DETAIL_RE.search(urlparse(url).path)
            if m:
                consultation = m.group(1)
                qs = parse_qs(urlparse(url).query)
                org = org or (qs.get("orgAcronyme") or qs.get("orgacronyme") or [""])[0]
                break
    if not consultation:
        return None
    detail = f"https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/{consultation}"
    if org:
        detail += f"?orgAcronyme={org}"
    return {"consultation_id": consultation, "org_acronym": org or None, "detail_url": detail}


def _recover_place_detail(candidate: dict, manifest: dict) -> str | None:
    title = _candidate_title(candidate)
    tokens = _distinctive_tokens(title)
    if len(tokens) < 2:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "FR_PLACE_SEARCH_ROUTE_RECOVERY_V22", "outcome": "INSUFFICIENT_TITLE_EVIDENCE"
        })
        return None
    search_url = "https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch"
    pw = browser = context = page = None
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(800)
        inputs = page.locator("input[type='text'], input:not([type])")
        try:
            meta = inputs.evaluate_all(
                """els => els.map((e,index)=>({index,id:e.id||'',name:e.name||'',placeholder:e.placeholder||'',aria:e.getAttribute('aria-label')||'',parent:((e.closest('label,.form-group,.field,.row')||e.parentElement)?.innerText||'').trim()}))"""
            )
        except Exception:
            meta = []
        chosen_index = None
        for item in meta or []:
            hay = _fold(" ".join(str(item.get(k) or "") for k in ("id", "name", "placeholder", "aria", "parent")))
            if ("reference" in hay and ("intitule" in hay or "objet" in hay or "consultation" in hay)) or "objet de la consultation" in hay:
                chosen_index = int(item.get("index"))
                break
        if chosen_index is None:
            # PLACE currently exposes one principal free-text consultation-search field.
            # Fail closed if we cannot identify it reasonably rather than filling a random input.
            manifest.setdefault("dce_method_attempts", []).append({
                "method": "FR_PLACE_SEARCH_ROUTE_RECOVERY_V22", "url": search_url,
                "outcome": "SEARCH_INPUT_NOT_IDENTIFIED", "inputs": (meta or [])[:30],
            })
            return None
        query = title[:180]
        target = inputs.nth(chosen_index)
        target.fill(query)
        target.press("Enter")
        page.wait_for_timeout(1800)
        try:
            page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass
        rows = _link_rows(page, PLACE_DETAIL_RE)
        chosen, scored = _pick_best_link(rows, candidate)
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "FR_PLACE_SEARCH_ROUTE_RECOVERY_V22",
            "url": search_url,
            "query": query,
            "resolved_url": page.url,
            "candidate_links": scored[:20],
            "outcome": "MATCHED" if chosen else "NO_UNAMBIGUOUS_MATCH",
        })
        return chosen
    except Exception as exc:
        _rethrow_http_probe_boundary(exc)
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "FR_PLACE_SEARCH_ROUTE_RECOVERY_V22", "url": search_url,
            "outcome": "ERROR", "error": repr(exc)[:700],
        })
        return None
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


def adapter_place_v22(candidate: dict, out: Path, manifest: dict):
    specific = _place_specific_route(candidate)
    if specific:
        trial = copy.deepcopy(candidate)
        route = dict(trial.get("route") or {})
        route.update({k: v for k, v in specific.items() if v})
        trial["route"] = route
        _OLD_PLACE_ADAPTER(trial, out, manifest)
        _sanitize_manifest_files(manifest)
        _refine_auth_from_redirect(manifest)
        return

    recovered = _recover_place_detail(candidate, manifest)
    if recovered:
        trial = copy.deepcopy(candidate)
        route = dict(trial.get("route") or {})
        m = PLACE_DETAIL_RE.search(urlparse(recovered).path)
        qs = parse_qs(urlparse(recovered).query)
        route["detail_url"] = recovered
        if m:
            route["consultation_id"] = m.group(1)
        org = (qs.get("orgAcronyme") or qs.get("orgacronyme") or [None])[0]
        if org:
            route["org_acronym"] = org
        route["place_search_recovered_v22"] = recovered
        trial["route"] = route
        manifest["fr_place_search_recovered_detail_v22"] = recovered
        _OLD_PLACE_ADAPTER(trial, out, manifest)
    else:
        # A generic PLACE root is not evidence of authentication being required.
        # Preserve it as an unresolved route so a future resolver can retry it.
        manifest["status"] = "TED_ROUTE_UNRESOLVED"
    _sanitize_manifest_files(manifest)
    _refine_auth_from_redirect(manifest)


def entry_match_v22(entry, candidate: dict) -> tuple[bool, str]:
    matched, method = _ORIGINAL_ENTRY_MATCH(entry, candidate)
    if matched:
        return matched, method
    wanted_title = _fold(_candidate_title(candidate))
    entry_title = _fold(placsp_atom.first(entry, "Name", "Title") or "")
    title_tokens = _distinctive_tokens(_candidate_title(candidate))
    if not wanted_title or wanted_title != entry_title or len(title_tokens) < 3:
        return False, ""
    wanted_buyer = _candidate_buyer(candidate)
    buyer_tokens = _distinctive_tokens(wanted_buyer)
    entry_text = _fold(" ".join(str(x.text or "") for x in entry.iter()))
    buyer_hits = [t for t in buyer_tokens if re.search(rf"\b{re.escape(t)}\b", entry_text)]
    if buyer_tokens and not buyer_hits:
        return False, ""
    # Exact normalized title plus buyer evidence (when available) is deterministic
    # enough to recover TED -> PLACSP linkage without fuzzy title matching.
    return True, "exact_title_buyer_v22" if buyer_tokens else "exact_distinctive_title_v22"


def _wrap_with_hygiene(adapter):
    if getattr(adapter, "_dce_v22_hygiene", False):
        return adapter
    def wrapped(candidate: dict, out: Path, manifest: dict):
        adapter(candidate, out, manifest)
        _sanitize_manifest_files(manifest)
        _refine_auth_from_redirect(manifest)
    wrapped._dce_v22_hygiene = True
    wrapped.__name__ = f"{getattr(adapter, '__name__', 'adapter')}_v22_hygiene"
    return wrapped


# Install conservative transport hygiene globally. All underlying bytes that are
# accepted as DCE files still follow the same V21 persistence and hashing logic.
base.looks_like_file = looks_like_file_v22
base.direct_download = direct_download_v22
v11._fileish_headers = _fileish_headers_v22
v15._entry_match = entry_match_v22

# Wrap the validated V21 adapter table, then override only the two route-recovery
# families that need extra V22 logic.
for _key, _adapter in list(base.ADAPTERS.items()):
    base.ADAPTERS[_key] = _wrap_with_hygiene(_adapter)
for _portal in ("CZ_NIPEZ", "CZ_NIPEZ_PUBLIC"):
    base.ADAPTERS[_portal] = adapter_nen_v22
base.ADAPTERS["FR_PLACE"] = adapter_place_v22


if __name__ == "__main__":
    v21.v20.install_http_probe_guard()
    v2.main()
