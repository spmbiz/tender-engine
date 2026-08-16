from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v4 as v4
import dce_worker_v9 as v9  # registers the full existing resolver stack first

FILE_HINT_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])", re.I)


def _http_urls(values) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in out:
            out.append(value)
    return out


def _route_urls(candidate: dict) -> list[str]:
    route = candidate.get("route") or {}
    urls: list[str] = []
    if isinstance(route, dict):
        urls.extend(_http_urls(route.get("document_urls") or []))
        for key in ("documents_url", "document_landing_url", "detail_url", "notice_url", "public_url"):
            value = route.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in urls:
                urls.append(value)
    for doc in candidate.get("documents") or []:
        value = doc.get("url") if isinstance(doc, dict) else doc
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in urls:
            urls.append(value)
    notice = candidate.get("notice_url")
    if isinstance(notice, str) and notice.startswith(("http://", "https://")) and notice not in urls:
        urls.append(notice)
    return urls


def _pcs_human_page(candidate: dict) -> str:
    route = candidate.get("route") or {}
    urls = _route_urls(candidate)
    # OCDS discovery can expose an API NoticeDownload URL as notice_url while the
    # actual anonymous PCS notice page is already present in route.document_urls.
    for url in urls:
        low = url.casefold()
        if "publiccontractsscotland.gov.uk/search/show/" in low:
            return url
    notice_ref = str((route.get("notice_ref") if isinstance(route, dict) else "") or candidate.get("notice_ref") or "").strip()
    if notice_ref:
        return f"https://www.publiccontractsscotland.gov.uk/search/show/search_view.aspx?ID={notice_ref}"
    for url in urls:
        if "publiccontractsscotland.gov.uk" in url.casefold() and "api.publiccontractsscotland" not in url.casefold():
            return url
    return ""


def adapter_pcs_v10(candidate: dict, out: Path, manifest: dict):
    """PCS resolver that understands both OCDS API routes and the human notice UI."""
    manifest.setdefault("dce_method_attempts", [])
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/10.0 public procurement research"})

    # Some NoticeDownload endpoints really are public attachments. Try them as
    # downloads first; never navigate a download endpoint as an HTML page.
    for url in _route_urls(candidate):
        if "api.publiccontractsscotland.gov.uk" not in url.casefold() and not FILE_HINT_RE.search(url):
            continue
        rec = base.direct_download(url, out, session)
        manifest["dce_method_attempts"].append({
            "method": "PCS_DIRECT_PUBLIC_FILE_V10", "url": url,
            "outcome": "DOWNLOADED" if rec else "NOT_FILE",
        })
        if rec:
            manifest.setdefault("files", []).append(rec)
    if manifest.get("files"):
        manifest["status"] = "DOWNLOADED_PUBLIC"
        return

    page_url = _pcs_human_page(candidate)
    if not page_url:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return

    pw = browser = context = page = None
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(900)
        body = page.locator("body").inner_text(timeout=15000)
        (out / "portal_page.txt").write_text(body[:800_000], encoding="utf-8")

        got = False
        # Existing PCS pages expose a download-all postback. Only invoke it when
        # the page actually contains the control/function; planned notices often
        # have no tender pack yet and should become NO_PUBLIC_FILE, not retryable.
        try:
            has_zip = page.locator("#ctl00_ContentPlaceHolder1_notice_add_docs1_lnkZip").count() > 0
            if has_zip:
                with page.expect_download(timeout=25000) as dl_info:
                    page.evaluate("() => __doPostBack('ctl00$ContentPlaceHolder1$notice_add_docs1$lnkZip','')")
                manifest.setdefault("files", []).append(base.persist_download(out, dl_info.value, page_url))
                got = True
                manifest["dce_method_attempts"].append({"method": "PCS_DOWNLOAD_ALL_POSTBACK_V10", "url": page_url, "outcome": "DOWNLOADED"})
        except Exception as exc:
            manifest["dce_method_attempts"].append({"method": "PCS_DOWNLOAD_ALL_POSTBACK_V10", "url": page_url, "outcome": "ERROR", "error": repr(exc)[:500]})

        if not got:
            # Capture any ordinary public attachment links the page exposes.
            try:
                anchors = page.locator("a[href]").evaluate_all(
                    "els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim()}))"
                )
            except Exception:
                anchors = []
            for item in anchors or []:
                href = str((item or {}).get("href") or "").strip()
                text = str((item or {}).get("text") or "").strip()
                if not href.startswith(("http://", "https://")):
                    continue
                if not (FILE_HINT_RE.search(href) or re.search(r"download|document|attachment|additional", f"{text} {href}", re.I)):
                    continue
                rec = base.direct_download(href, out, session)
                if rec:
                    manifest.setdefault("files", []).append(rec)
                    got = True

        if got:
            manifest["status"] = "DOWNLOADED_PUBLIC"
        elif re.search(r"record(?:ing)? (?:your )?interest|register interest", body, re.I):
            manifest["status"] = "INTEREST_RECORDING_REQUIRED"
        elif re.search(r"login|sign in|log in", body, re.I):
            manifest["status"] = "AUTH_REQUIRED"
        else:
            manifest["status"] = "NO_PUBLIC_FILE"
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
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


def _rhr_detail_url(candidate: dict) -> str:
    route = candidate.get("route") or {}
    for key in ("document_landing_url", "detail_url", "notice_url"):
        value = route.get(key) if isinstance(route, dict) else None
        if isinstance(value, str) and "riigihanked.riik.ee" in value.casefold():
            return value
    notice = candidate.get("notice_url")
    return notice if isinstance(notice, str) and "riigihanked.riik.ee" in notice.casefold() else ""


def _rhr_click_download(page, out: Path, manifest: dict, source_url: str, timeout: int = 12000) -> bool:
    patterns = [
        re.compile(r"Laadi alla kehtivad hanke dokumendid", re.I),
        re.compile(r"Laadi alla.*dokumendid", re.I),
        re.compile(r"Download.*procurement documents", re.I),
        re.compile(r"Download.*documents", re.I),
    ]
    for pattern in patterns:
        for selector in ("button", "a", "[role='button']"):
            try:
                loc = page.locator(selector).filter(has_text=pattern)
                for i in range(min(loc.count(), 4)):
                    node = loc.nth(i)
                    if not node.is_visible():
                        continue
                    try:
                        with page.expect_download(timeout=timeout) as dl_info:
                            node.click(force=True, timeout=5000)
                        manifest.setdefault("files", []).append(base.persist_download(out, dl_info.value, source_url))
                        manifest.setdefault("dce_method_attempts", []).append({"method": "EE_RHR_UI_DOWNLOAD_V10", "url": source_url, "outcome": "DOWNLOADED"})
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
    return False


def adapter_ee_rhr_v10(candidate: dict, out: Path, manifest: dict):
    """Use RHR's anonymous SPA download controls instead of HTTP-fetching # routes."""
    manifest.setdefault("dce_method_attempts", [])
    detail_url = _rhr_detail_url(candidate)
    route = candidate.get("route") or {}
    if not detail_url:
        return v4.cascade_public_adapter(candidate, out, manifest)

    pw = browser = context = page = None
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2200)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            body = page.locator("body").inner_text(timeout=15000)
            (out / "portal_page.txt").write_text(body[:800_000], encoding="utf-8")
        except Exception:
            body = ""

        if _rhr_click_download(page, out, manifest, page.url):
            manifest["status"] = "DOWNLOADED_PUBLIC"
            return

        # Individual source-document URLs are SPA fragment routes. Navigate them
        # in the browser, then click their visible download control; sending the
        # fragment URL to requests only returns the application shell.
        doc_urls = _http_urls(route.get("document_urls") or []) if isinstance(route, dict) else []
        for doc_url in doc_urls[:8]:
            if "riigihanked.riik.ee" not in doc_url.casefold():
                continue
            try:
                page.goto(doc_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1400)
                if _rhr_click_download(page, out, manifest, page.url, timeout=8000):
                    if len(manifest.get("files") or []) >= 8:
                        break
            except Exception as exc:
                manifest["dce_method_attempts"].append({"method": "EE_RHR_SOURCE_DOCUMENT_V10", "url": doc_url, "outcome": "ERROR", "error": repr(exc)[:500]})

        if manifest.get("files"):
            manifest["status"] = "DOWNLOADED_PUBLIC"
            return
    except Exception as exc:
        manifest["dce_method_attempts"].append({"method": "EE_RHR_BROWSER_V10", "url": detail_url, "outcome": "ERROR", "error": repr(exc)[:700]})
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

    # Preserve the old guarded cascade as a fallback. It remains fail-closed and
    # cannot turn an HTML shell into DCE evidence.
    return v4.cascade_public_adapter(candidate, out, manifest)


def _world_bank_notice_id(candidate: dict) -> str:
    values = [candidate.get("notice_url"), candidate.get("candidate_id"), candidate.get("notice_id")]
    route = candidate.get("route") or {}
    if isinstance(route, dict):
        values.extend([route.get("notice_id"), route.get("procurement_notice_id")])
    for value in values:
        match = re.search(r"\bOP\d{6,}\b", str(value or ""), re.I)
        if match:
            return match.group(0).upper()
    return ""


def _world_bank_records(payload) -> list[dict]:
    records = payload.get("procnotices") if isinstance(payload, dict) else None
    if isinstance(records, list):
        return [x for x in records if isinstance(x, dict)]
    if isinstance(records, dict):
        return [x for x in records.values() if isinstance(x, dict)]
    return []


def adapter_world_bank_v10(candidate: dict, out: Path, manifest: dict):
    """Resolve World Bank notices through the official public Procurement API.

    The projects.worldbank.org HTML detail page currently returns 403 to the generic
    downloader. The official search.worldbank.org procurement API is public and
    contains the authoritative notice text plus any embedded public links.
    """
    manifest.setdefault("dce_method_attempts", [])
    notice_id = _world_bank_notice_id(candidate)
    if not notice_id:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return

    api_url = "https://search.worldbank.org/api/procnotices"
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/10.0 public procurement research", "Accept": "application/json"})
    try:
        response = session.get(api_url, params={"format": "json", "rows": "25", "qterm": notice_id}, timeout=45)
        attempt = {"method": "WORLD_BANK_PROCUREMENT_API_V10", "url": response.url, "http_status": response.status_code, "bytes": len(response.content)}
        manifest["dce_method_attempts"].append(attempt)
        response.raise_for_status()
        payload = response.json()
        records = _world_bank_records(payload)
        record = next((r for r in records if str(r.get("id") or "").upper() == notice_id), None)
        if record is None:
            attempt["outcome"] = "NOTICE_ID_NOT_FOUND"
            manifest["status"] = "NO_PUBLIC_FILE"
            return
        attempt["outcome"] = "NOTICE_FOUND"
        (out.parent / "world_bank_api_record.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

        notice_text = str(record.get("notice_text") or "").strip()
        if notice_text:
            rec = base.persist_bytes(
                out,
                f"world_bank_procurement_notice_{notice_id}.html",
                notice_text.encode("utf-8"),
                response.url,
                "text/html; charset=utf-8",
            )
            manifest.setdefault("files", []).append(rec)
            manifest["world_bank_notice_authority"] = "OFFICIAL_PROCUREMENT_NOTICES_API"

        # The official notice body may link to borrower-hosted bidding documents.
        # Download only links that actually validate as files.
        for href in re.findall(r"href=[\"']([^\"']+)[\"']", html.unescape(notice_text), re.I)[:80]:
            url = urljoin("https://www.worldbank.org/", href.strip())
            if not url.startswith(("http://", "https://")):
                continue
            rec = base.direct_download(url, out, session)
            if rec:
                manifest.setdefault("files", []).append(rec)

        manifest["status"] = "DOWNLOADED_PUBLIC" if manifest.get("files") else "NO_PUBLIC_FILE"
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
        manifest["dce_method_attempts"].append({"method": "WORLD_BANK_PROCUREMENT_API_V10", "outcome": "ERROR", "error": repr(exc)[:700]})


# Override only the live lanes proven broken in fanout 31974706689. Everything
# else remains exactly on the v9 stack.
base.ADAPTERS["SCOTLAND_PCS"] = adapter_pcs_v10
base.ADAPTERS["EE_RHR"] = adapter_ee_rhr_v10
base.ADAPTERS["WORLD_BANK"] = adapter_world_bank_v10

if __name__ == "__main__":
    v2.main()
