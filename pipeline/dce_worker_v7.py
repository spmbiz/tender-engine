from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v4 as v4
import dce_worker_v6 as v6  # noqa: F401 - register all existing v6 adapters first

DOC_SIGNAL_RE = re.compile(
    r"vergabeunterlag|ausschreibungsunterlag|procurement document|tender document|"
    r"download|dokument|unterlag|bieter|teilnahme|eformsbekvuurl|\.pdf(?:$|[?#])|"
    r"\.zip(?:$|[?#])|\.docx?(?:$|[?#])|\.xlsx?(?:$|[?#])",
    re.I,
)
NAV_TEXT_RE = re.compile(r"privacy|datenschutz|impressum|faq|kontakt|contact|home|startseite|barrierefreiheit", re.I)
SAM_ATTACHMENT_RE = re.compile(
    r"attachment|download|resource|document|statement of work|scope of work|performance work statement|"
    r"\bpws\b|\bsow\b|solicitation|rfq|rfp|pricing|amendment|\.pdf|\.zip|\.docx?|\.xlsx?|\.xls|\.pptx?",
    re.I,
)


def _de_browser_links(url: str, out: Path, manifest: dict) -> list[tuple[int, str, str]]:
    pw = browser = context = page = None
    found: list[tuple[int, str, str]] = []
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        body = page.locator("body").inner_text(timeout=15000)
        if body:
            (out / "portal_page.txt").write_text(body[:800_000], encoding="utf-8")
        anchors = page.locator("a[href]").evaluate_all(
            "els => els.map(a => ({href: a.href || '', text: (a.innerText || a.textContent || '').trim()}))"
        )
        page_host = (urlparse(page.url).hostname or "").casefold()
        seen = set()
        for a in anchors or []:
            href = str((a or {}).get("href") or "").strip()
            text = re.sub(r"\s+", " ", str((a or {}).get("text") or "")).strip()
            if not href.startswith(("http://", "https://")) or href in seen:
                continue
            seen.add(href)
            host = (urlparse(href).hostname or "").casefold()
            hay = f"{text} {href}"
            score = 0
            if DOC_SIGNAL_RE.search(hay): score += 8
            if host and host != page_host: score += 3
            if re.search(r"vergabeunterlagen|procurement document|tender document", text, re.I): score += 8
            if re.search(r"\.pdf|\.zip|\.docx?|\.xlsx?", href, re.I): score += 7
            if NAV_TEXT_RE.search(text) and score < 8: continue
            if score > 0:
                found.append((score, href, text[:300]))
        found.sort(key=lambda x: (-x[0], x[1]))
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "DE_DOE_RENDERED_DETAIL",
            "url": url,
            "outcome": "LINKS_FOUND" if found else "NO_DOCUMENT_LINKS",
            "candidate_links": [{"score": s, "url": h, "text": t} for s, h, t in found[:40]],
        })
        return found[:40]
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "DE_DOE_RENDERED_DETAIL", "url": url, "outcome": "ERROR", "error": repr(exc)[:600]
        })
        return []
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


def adapter_germany_doe(candidate: dict, out: Path, manifest: dict):
    """Resolve JS-rendered oeffentlichevergabe.de notice details to public docs/portals.

    No login, CAPTCHA bypass, or interest-registration automation is attempted.
    """
    manifest.setdefault("dce_method_attempts", [])
    if v4._attempt_direct(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    route_urls = [(m, u) for m, u in v4._route_urls(candidate) if m != "DIRECT_DOCUMENT"]
    rendered: list[tuple[int, str, str]] = []
    for method, url in route_urls:
        if "oeffentlichevergabe.de" in url.casefold():
            rendered.extend(_de_browser_links(url, out, manifest))
    dedup = []
    seen = set()
    for score, url, text in sorted(rendered, key=lambda x: (-x[0], x[1])):
        if url not in seen:
            seen.add(url); dedup.append((score, url, text))

    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/7.0 public procurement research"})
    statuses = []
    for score, url, text in dedup[:30]:
        rec = base.direct_download(url, out, session)
        manifest["dce_method_attempts"].append({
            "method": "DE_DOE_RENDERED_LINK_DIRECT", "url": url, "link_text": text,
            "score": score, "outcome": "DOWNLOADED" if rec else "NOT_FILE"
        })
        if rec:
            manifest["files"].append(rec)
            manifest["status"] = "DOWNLOADED_PUBLIC"
            return
        if score >= 8:
            status = v4._try_page(candidate, url, out, manifest, "DE_DOE_LINKED_PROCUREMENT_PAGE")
            statuses.append(status)
            if manifest.get("files"):
                manifest["status"] = "DOWNLOADED_PUBLIC"
                return

    v4.cascade_public_adapter(candidate, out, manifest)
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return
    if any(s in statuses for s in ("AUTH_REQUIRED", "CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED")):
        for s in ("CAPTCHA_REQUIRED", "AUTH_REQUIRED", "INTEREST_RECORDING_REQUIRED"):
            if s in statuses:
                manifest["status"] = s
                return


def _sam_notice_id(candidate: dict) -> str:
    for value in (
        candidate.get("opportunity_id"), candidate.get("notice_id"),
        (candidate.get("route") or {}).get("opportunity_id"),
    ):
        s = str(value or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{32}", s):
            return s
    cid = str(candidate.get("candidate_id") or "")
    m = re.search(r"US-SAM:([0-9a-fA-F]{32})", cid, re.I)
    if m:
        return m.group(1)
    for value in (candidate.get("notice_url"), (candidate.get("route") or {}).get("detail_url")):
        m = re.search(r"/opp/([0-9a-fA-F]{32})/view", str(value or ""), re.I)
        if m:
            return m.group(1)
    return ""


def _sam_public_url(candidate: dict) -> str:
    nid = _sam_notice_id(candidate)
    if nid:
        return f"https://sam.gov/opp/{nid}/view"
    raw = str(candidate.get("notice_url") or (candidate.get("route") or {}).get("detail_url") or "").strip()
    return re.sub(r"https://sam\.gov/workspace/contract/opp/([^/]+)/view", r"https://sam.gov/opp/\1/view", raw, flags=re.I)


def _sam_api_resource_links(candidate: dict, manifest: dict) -> list[str]:
    """Optional accelerator using the official Get Opportunities Public API."""
    key = str(os.getenv("SAM_API_KEY") or "").strip()
    nid = _sam_notice_id(candidate)
    if not key or not nid:
        return []
    try:
        r = requests.get(
            "https://api.sam.gov/opportunities/v2/search",
            params={"api_key": key, "noticeid": nid, "limit": 10, "offset": 0},
            headers={"User-Agent": "Tender-Engine/7.1 public procurement research"},
            timeout=45,
        )
        attempt = {"method": "SAM_GET_OPPORTUNITIES_API", "http_status": r.status_code, "bytes": len(r.content)}
        manifest.setdefault("dce_method_attempts", []).append(attempt)
        if not r.ok:
            return []
        data = r.json()
        links: list[str] = []
        for row in data.get("opportunitiesData") or []:
            if not isinstance(row, dict):
                continue
            for u in row.get("resourceLinks") or []:
                if isinstance(u, str) and u.startswith(("http://", "https://")):
                    links.append(u)
        attempt["resource_links"] = len(links)
        return list(dict.fromkeys(links))
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({"method": "SAM_GET_OPPORTUNITIES_API", "outcome": "ERROR", "error": repr(exc)[:500]})
        return []


def _sam_rendered_links(candidate: dict, out: Path, manifest: dict) -> tuple[list[str], str]:
    """Discover public supplier attachment links from SAM's /opp/<id>/view surface."""
    url = _sam_public_url(candidate)
    if not url:
        return [], ""
    pw = browser = context = page = None
    found: list[tuple[int, str, str]] = []
    body = ""
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2200)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        try:
            body = page.locator("body").inner_text(timeout=15000)
            if body:
                (out / "portal_page.txt").write_text(body[:2_000_000], encoding="utf-8")
        except Exception:
            body = ""
        anchors = page.locator("a[href]").evaluate_all(
            "els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim(), aria:a.getAttribute('aria-label')||'', title:a.getAttribute('title')||''}))"
        )
        seen = set()
        for a in anchors or []:
            href = str((a or {}).get("href") or "").strip()
            text = re.sub(r"\s+", " ", " ".join(str((a or {}).get(k) or "") for k in ("text", "aria", "title"))).strip()
            if not href.startswith(("http://", "https://")) or href in seen:
                continue
            seen.add(href)
            hay = f"{text} {href}"
            score = 0
            if SAM_ATTACHMENT_RE.search(hay): score += 8
            if re.search(r"/resources?/|attachment|download", href, re.I): score += 8
            if re.search(r"\.pdf|\.zip|\.docx?|\.xlsx?|\.xls|\.pptx?", href, re.I): score += 8
            if "sam.gov/opp/" in href.casefold() and "/view" in href.casefold() and score < 12:
                continue
            if score:
                found.append((score, href, text[:300]))
        # Some SAM attachment endpoints are materialized by JS/XHR and never become
        # obvious static anchors. Resource timing still exposes the public endpoint.
        try:
            perf = page.evaluate("performance.getEntriesByType('resource').map(e => e.name)") or []
            for href in perf:
                href = str(href or "").strip()
                if href.startswith(("http://", "https://")) and re.search(r"attachment|/resources?/|download", href, re.I):
                    if href not in seen:
                        seen.add(href); found.append((7, href, "browser-resource"))
        except Exception:
            pass
        found.sort(key=lambda x: (-x[0], x[1]))
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "SAM_PUBLIC_RENDERED_ATTACHMENTS", "url": url,
            "resolved_url": str(page.url), "outcome": "LINKS_FOUND" if found else "NO_DOCUMENT_LINKS",
            "candidate_links": [{"score": s, "url": h, "text": t} for s, h, t in found[:60]],
            "public_page_loaded": bool(body),
        })
        return [h for _, h, _ in found[:60]], body
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({"method": "SAM_PUBLIC_RENDERED_ATTACHMENTS", "url": url, "outcome": "ERROR", "error": repr(exc)[:600]})
        return [], body
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


def adapter_sam_public(candidate: dict, out: Path, manifest: dict):
    """Public supplier-side SAM resolver; never uses the authenticated federal workspace."""
    manifest.setdefault("dce_method_attempts", [])
    if v4._attempt_direct(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    urls = _sam_api_resource_links(candidate, manifest)
    body = ""
    rendered, body = _sam_rendered_links(candidate, out, manifest)
    urls.extend(rendered)
    urls = list(dict.fromkeys(u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))))
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/7.1 public procurement research", "Referer": _sam_public_url(candidate)})
    for url in urls[:60]:
        rec = base.direct_download(url, out, session)
        manifest["dce_method_attempts"].append({"method": "SAM_PUBLIC_ATTACHMENT_DIRECT", "url": url, "outcome": "DOWNLOADED" if rec else "NOT_FILE"})
        if rec:
            manifest["files"].append(rec)
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    # A public SAM page can contain a global Sign In control even when the notice is
    # fully public. Never infer AUTH_REQUIRED from that navigation boilerplate.
    if re.search(r"controlled unclassified|request access|explicit access|export controlled", body or "", re.I):
        manifest["status"] = "AUTH_REQUIRED"
    elif body:
        manifest["status"] = "NO_PUBLIC_FILE"
    else:
        manifest["status"] = "ERROR_RETRYABLE"


base.ADAPTERS["DE_DOE"] = adapter_germany_doe
base.ADAPTERS["US_SAM"] = adapter_sam_public
base.ADAPTERS["US_SAM_BULK"] = adapter_sam_public

if __name__ == "__main__":
    v2.main()
