from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v4 as v4
import dce_worker_v7 as v7  # registers all previous adapters first

SAM_SIGNAL_RE = re.compile(r"attachment|resource|download|opportunit|solicitation", re.I)
SAM_FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])", re.I)
RESOURCE_ID_RE = re.compile(r"\b[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}\b")
FALSE_LINKS = {
    "https://sam.gov/about/external-resources",
    "https://sam.gov/about/help",
}


def _walk_json(obj, urls: list[str], resource_ids: list[str], metadata: list[dict], path: str = "root"):
    if isinstance(obj, dict):
        low = {str(k).casefold(): v for k, v in obj.items()}
        rid = next((str(low[k]).strip() for k in ("resourceid", "resource_id") if k in low and low[k]), "")
        rname = next((str(low[k]).strip() for k in ("resourcename", "filename", "file_name", "name") if k in low and low[k]), "")
        access = next((str(low[k]).strip() for k in ("packageaccesslevel", "access", "explicitaccess") if k in low and low[k] is not None), "")
        if rid:
            resource_ids.append(rid)
            metadata.append({"path": path, "resource_id": rid, "name": rname[:300], "access": access[:120]})
        for k, v in obj.items():
            key = str(k).casefold()
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                if SAM_SIGNAL_RE.search(key) or SAM_FILE_RE.search(v) or "/resources/" in v.casefold():
                    urls.append(v)
            _walk_json(v, urls, resource_ids, metadata, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2000]):
            _walk_json(v, urls, resource_ids, metadata, f"{path}[{i}]")
    elif isinstance(obj, str):
        if obj.startswith(("http://", "https://")) and (SAM_FILE_RE.search(obj) or "/resources/" in obj.casefold()):
            urls.append(obj)


def _resource_download_candidates(resource_ids: list[str]) -> list[str]:
    out = []
    for rid in resource_ids:
        rid = str(rid).strip()
        if not rid:
            continue
        # Known SAM resource route families. These are only candidates; direct_download
        # validates content before any file is accepted as DCE evidence.
        out.extend([
            f"https://api.sam.gov/prod/opportunities/v1/resources/files/{rid}/download",
            f"https://api.sam.gov/opportunities/v1/resources/files/{rid}/download",
            f"https://sam.gov/api/prod/opportunities/v1/resources/files/{rid}/download",
        ])
    return list(dict.fromkeys(out))


def _attachment_section_text(page) -> str:
    """Return only local attachment-panel text, never the global SAM footer."""
    snippets = []
    selectors = [
        "section:has-text('Attachments/Links')",
        "div:has-text('Attachments/Links')",
        "sam-entity-section:has-text('Attachments')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 8)
            for i in range(count):
                text = loc.nth(i).inner_text(timeout=2500)
                if text and "Attachments" in text and len(text) < 100_000:
                    snippets.append(text)
        except Exception:
            pass
    # Prefer the shortest matching container because broad ancestors often include footer CUI.
    if snippets:
        return min(snippets, key=len)[:100_000]
    try:
        body = page.locator("body").inner_text(timeout=4000)
        idx = body.casefold().find("attachments/links")
        if idx >= 0:
            return body[idx:idx + 5000]
    except Exception:
        pass
    return ""


def _expand_attachments(page) -> list[str]:
    clicked = []
    selectors = [
        "button:has-text('Attachments')",
        "[role='button']:has-text('Attachments')",
        "a:has-text('Attachments')",
        "button:has-text('Download All Attachments')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 8)):
                node = loc.nth(i)
                try:
                    if not node.is_visible():
                        continue
                    text = re.sub(r"\s+", " ", node.inner_text(timeout=1500) or "").strip()
                    # Do not click Download All yet; first expand the section and capture metadata.
                    if "download all" in text.casefold():
                        continue
                    node.click(timeout=4000)
                    clicked.append(text[:200] or sel)
                    page.wait_for_timeout(1200)
                except Exception:
                    continue
        except Exception:
            continue
    return list(dict.fromkeys(clicked))


def _sam_rendered_links_v8(candidate: dict, out: Path, manifest: dict) -> tuple[list[str], str, str]:
    url = v7._sam_public_url(candidate)
    if not url:
        return [], "", ""
    notice_id = v7._sam_notice_id(candidate)
    pw = browser = context = page = None
    body = ""
    network_rows: list[dict] = []
    json_payloads: list[dict] = []
    found_urls: list[str] = []
    resource_ids: list[str] = []
    resource_meta: list[dict] = []

    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()

        def on_response(resp):
            try:
                rurl = str(resp.url or "")
                ctype = str((resp.headers or {}).get("content-type") or "")
                interesting = bool(
                    (notice_id and notice_id.casefold() in rurl.casefold())
                    or SAM_SIGNAL_RE.search(rurl)
                    or "api.sam.gov" in rurl.casefold()
                    or "sam.gov/api" in rurl.casefold()
                )
                if interesting:
                    network_rows.append({"url": rurl[:2000], "status": resp.status, "content_type": ctype[:200]})
                if "json" not in ctype.casefold():
                    return
                # Parse only plausible SAM/API JSON responses and cap stored diagnostics.
                if not interesting and "sam.gov" not in (urlparse(rurl).hostname or "").casefold():
                    return
                raw = resp.text()
                if not raw or len(raw) > 4_000_000:
                    return
                low = raw.casefold()
                if not any(x in low for x in ("resourceid", "resourcelinks", "attachment", "packageaccesslevel", notice_id.casefold() if notice_id else "__none__")):
                    return
                try:
                    data = json.loads(raw)
                except Exception:
                    return
                urls: list[str] = []
                ids: list[str] = []
                meta: list[dict] = []
                _walk_json(data, urls, ids, meta)
                found_urls.extend(urls)
                resource_ids.extend(ids)
                resource_meta.extend(meta)
                json_payloads.append({
                    "url": rurl[:2000],
                    "status": resp.status,
                    "keys": list(data)[:40] if isinstance(data, dict) else [],
                    "urls_found": urls[:40],
                    "resource_ids": ids[:40],
                    "resource_meta": meta[:40],
                })
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass

        clicked = _expand_attachments(page)
        page.wait_for_timeout(1800)

        try:
            body = page.locator("body").inner_text(timeout=12000)
            if body:
                (out / "portal_page.txt").write_text(body[:2_000_000], encoding="utf-8")
        except Exception:
            body = ""
        section_text = _attachment_section_text(page)
        if section_text:
            (out / "sam_attachment_section.txt").write_text(section_text, encoding="utf-8")

        # Collect visible links and button/control metadata after expansion.
        dom = []
        try:
            dom = page.locator("a[href],button,[role='button'],[role='link']").evaluate_all(
                "els => els.map(e => ({tag:e.tagName, href:e.href||'', text:(e.innerText||e.textContent||'').trim(), aria:e.getAttribute('aria-label')||'', title:e.getAttribute('title')||'', id:e.id||'', cls:e.className||'', data:[...e.attributes].filter(a=>a.name.startsWith('data-')).reduce((o,a)=>(o[a.name]=a.value,o),{})}))"
            )
        except Exception:
            pass
        seen = set()
        dom_debug = []
        for e in dom or []:
            href = str((e or {}).get("href") or "").strip()
            text = re.sub(r"\s+", " ", " ".join(str((e or {}).get(k) or "") for k in ("text", "aria", "title", "id", "cls"))).strip()
            data = (e or {}).get("data") or {}
            hay = f"{text} {href} {json.dumps(data, ensure_ascii=False)}"
            if SAM_SIGNAL_RE.search(hay) or (notice_id and notice_id.casefold() in hay.casefold()):
                dom_debug.append({"tag": (e or {}).get("tag"), "href": href[:2000], "text": text[:500], "data": data})
            if href.startswith(("http://", "https://")) and href not in seen:
                seen.add(href)
                if href in FALSE_LINKS or "/about/external-resources" in href.casefold():
                    continue
                if SAM_FILE_RE.search(href) or re.search(r"/resources?/|attachment|download", href, re.I):
                    found_urls.append(href)
            for value in list(data.values()) if isinstance(data, dict) else []:
                sv = str(value or "")
                if RESOURCE_ID_RE.fullmatch(sv):
                    resource_ids.append(sv)

        # HTML may carry resource IDs even if the controls do not expose hrefs.
        try:
            html_text = page.content()
            for rid in RESOURCE_ID_RE.findall(html_text):
                if rid.casefold() != notice_id.casefold() if notice_id else True:
                    resource_ids.append(rid)
        except Exception:
            pass

        # Resource Timing is useful even when response body hooks miss a cached request.
        try:
            perf = page.evaluate("performance.getEntriesByType('resource').map(e => e.name)") or []
            for rurl in perf:
                rurl = str(rurl or "").strip()
                if not rurl.startswith(("http://", "https://")):
                    continue
                if "sam.gov/about/external-resources" in rurl.casefold():
                    continue
                if (notice_id and notice_id.casefold() in rurl.casefold()) or SAM_SIGNAL_RE.search(rurl):
                    network_rows.append({"url": rurl[:2000], "status": None, "content_type": "performance"})
                if SAM_FILE_RE.search(rurl) or re.search(r"/resources?/.*download|attachment", rurl, re.I):
                    found_urls.append(rurl)
        except Exception:
            pass

        found_urls.extend(_resource_download_candidates(list(dict.fromkeys(resource_ids))))
        found_urls = [u for u in dict.fromkeys(found_urls) if u not in FALSE_LINKS and "/about/external-resources" not in u.casefold()]
        network_rows = list({(x.get("url"), x.get("status"), x.get("content_type")): x for x in network_rows}.values())

        diagnostics = {
            "method": "SAM_PUBLIC_XHR_ATTACHMENTS_V8",
            "url": url,
            "resolved_url": str(page.url),
            "clicked_controls": clicked,
            "attachment_section_preview": section_text[:4000],
            "attachment_access_requested": bool(re.search(r"attachments?/links.{0,1500}request access|request access.{0,1500}attachments?/links", section_text, re.I | re.S)),
            "candidate_urls": found_urls[:100],
            "resource_ids": list(dict.fromkeys(resource_ids))[:100],
            "resource_meta": resource_meta[:100],
            "network": network_rows[:200],
            "json_payloads": json_payloads[:50],
            "dom_controls": dom_debug[:120],
            "public_page_loaded": bool(body),
        }
        manifest.setdefault("dce_method_attempts", []).append(diagnostics)
        (out / "sam_network_diagnostics.json").write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")
        return found_urls[:100], body, section_text
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append({
            "method": "SAM_PUBLIC_XHR_ATTACHMENTS_V8", "url": url, "outcome": "ERROR", "error": repr(exc)[:800]
        })
        return [], body, ""
    finally:
        try:
            if page: page.close()
        except Exception:
            pass
        try:
            if browser: browser.close()
        except Exception:
            pass
        try:
            if pw: pw.stop()
        except Exception:
            pass


def adapter_sam_public_v8(candidate: dict, out: Path, manifest: dict):
    """Supplier-side SAM resolver with attachment-panel + XHR discovery."""
    manifest.setdefault("dce_method_attempts", [])
    if v4._attempt_direct(candidate, out, manifest):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    urls = list(v7._sam_api_resource_links(candidate, manifest))
    rendered, body, section_text = _sam_rendered_links_v8(candidate, out, manifest)
    urls.extend(rendered)
    urls = list(dict.fromkeys(u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))))

    # Try ordinary HTTP first. If SAM generated a short-lived browser-authenticated
    # URL this may fail harmlessly; the canary diagnostics still expose the route.
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Tender-Engine/8.0 public procurement research",
        "Referer": v7._sam_public_url(candidate),
    })
    for u in urls[:100]:
        if u in FALSE_LINKS or "/about/external-resources" in u.casefold():
            continue
        rec = base.direct_download(u, out, session)
        manifest["dce_method_attempts"].append({
            "method": "SAM_PUBLIC_ATTACHMENT_DIRECT_V8", "url": u,
            "outcome": "DOWNLOADED" if rec else "NOT_FILE",
        })
        if rec:
            manifest["files"].append(rec)
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    # Only attachment-local access controls can imply AUTH_REQUIRED. Global footer
    # CUI/security language and SAM's Sign In navigation are never sufficient.
    if re.search(r"request access|controlled attachment|explicit access", section_text or "", re.I):
        manifest["status"] = "AUTH_REQUIRED"
    elif body:
        manifest["status"] = "NO_PUBLIC_FILE"
    else:
        manifest["status"] = "ERROR_RETRYABLE"


base.ADAPTERS["US_SAM"] = adapter_sam_public_v8
base.ADAPTERS["US_SAM_BULK"] = adapter_sam_public_v8

if __name__ == "__main__":
    v2.main()
