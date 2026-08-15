from __future__ import annotations

import html
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
        # High-signal external procurement pages may expose the actual files one hop later.
        if score >= 8:
            status = v4._try_page(candidate, url, out, manifest, "DE_DOE_LINKED_PROCUREMENT_PAGE")
            statuses.append(status)
            if manifest.get("files"):
                manifest["status"] = "DOWNLOADED_PUBLIC"
                return

    # Fall back to the proven generic cascade so current behavior is never lost.
    v4.cascade_public_adapter(candidate, out, manifest)
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return
    if any(s in statuses for s in ("AUTH_REQUIRED", "CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED")):
        for s in ("CAPTCHA_REQUIRED", "AUTH_REQUIRED", "INTEREST_RECORDING_REQUIRED"):
            if s in statuses:
                manifest["status"] = s
                return


base.ADAPTERS["DE_DOE"] = adapter_germany_doe

if __name__ == "__main__":
    v2.main()
