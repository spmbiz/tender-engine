from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name: str, fallback: str = "download.bin") -> str:
    name = Path(name or fallback).name
    name = re.sub(r"[^A-Za-z0-9._() \-]+", "_", name).strip()
    return (name or fallback)[:180]


def slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:100]


def load_candidate(queue: Path, line_no: int) -> dict:
    with queue.open("r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, start=1):
            if n != line_no:
                continue
            line = line.strip()
            if not line:
                break
            obj = json.loads(line)
            if not isinstance(obj, dict):
                break
            return obj
    raise SystemExit(f"No JSON candidate found at line {line_no} in {queue}")


def persist_bytes(out: Path, name: str, body: bytes, source_url: str | None = None, content_type: str | None = None) -> dict:
    filename = safe_name(name)
    path = out / filename
    if path.exists():
        stem, suffix = path.stem, path.suffix
        i = 2
        while path.exists():
            path = out / f"{stem}_{i}{suffix}"
            i += 1
    path.write_bytes(body)
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "source_url": source_url,
        "content_type": content_type,
    }


def persist_download(out: Path, download, source_url: str | None = None) -> dict:
    filename = safe_name(download.suggested_filename or "download.bin")
    path = out / filename
    if path.exists():
        stem, suffix = path.stem, path.suffix
        i = 2
        while path.exists():
            path = out / f"{stem}_{i}{suffix}"
            i += 1
    download.save_as(str(path))
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "source_url": source_url,
        "content_type": None,
    }


def looks_like_file(resp: requests.Response) -> bool:
    ct = (resp.headers.get("content-type") or "").lower()
    cd = (resp.headers.get("content-disposition") or "").lower()
    if "attachment" in cd:
        return True
    if any(x in ct for x in ("application/pdf", "application/zip", "application/octet-stream", "application/vnd", "text/csv")):
        return True
    path = urlparse(resp.url).path.lower()
    return bool(re.search(r"\.(pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)$", path)) and "text/html" not in ct


def filename_from_response(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition") or ""
    m = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", cd, re.I)
    if m:
        return safe_name(html.unescape(m.group(1)).strip())
    name = Path(urlparse(resp.url).path).name
    return safe_name(name or fallback)


def direct_download(url: str, out: Path, session: requests.Session) -> dict | None:
    try:
        r = session.get(url, timeout=45, allow_redirects=True)
        if r.ok and r.content and looks_like_file(r):
            return persist_bytes(out, filename_from_response(r, "download.bin"), r.content, r.url, r.headers.get("content-type"))
    except Exception:
        return None
    return None


def adapter_direct(candidate: dict, out: Path, manifest: dict):
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/2.0 public procurement research"})
    urls = []
    route = candidate.get("route") or {}
    urls.extend(route.get("document_urls") or [])
    for d in candidate.get("documents") or []:
        if isinstance(d, dict) and d.get("url"):
            urls.append(d["url"])
        elif isinstance(d, str):
            urls.append(d)
    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        file_rec = direct_download(url, out, session)
        if file_rec:
            manifest["files"].append(file_rec)
    manifest["status"] = "DOWNLOADED_PUBLIC" if manifest["files"] else "DOWNSTREAM_PORTAL_OR_NO_PUBLIC_FILE"


def adapter_ungm(candidate: dict, out: Path, manifest: dict):
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/2.0 public procurement research"})
    route = candidate.get("route") or {}
    notice_id = str(route.get("notice_id") or candidate.get("notice_id") or "").strip()
    notice_url = candidate.get("notice_url") or (f"https://www.ungm.org/Public/Notice/{notice_id}" if notice_id else None)
    if not notice_url:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return
    try:
        page = session.get(notice_url, timeout=45)
        page.raise_for_status()
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
        return
    text = html.unescape(page.text)
    urls = set()
    for m in re.findall(r"(?:href=[\"']([^\"']*DownloadDocument[^\"']+)|https?://[^\s\"'<>]+DownloadDocument[^\s\"'<>]+)", text, re.I):
        if isinstance(m, tuple):
            u = next((x for x in m if x), "")
        else:
            u = m
        if u:
            urls.add(urljoin(notice_url, u.replace("&amp;", "&")))
    if notice_id:
        # Download-all is useful if exposed, but individual links are more deterministic.
        for m in re.finditer(r"documentId=([A-Za-z0-9_-]+)", text):
            urls.add(f"https://www.ungm.org/Public/Notice/DownloadDocument?noticeId={notice_id}&documentId={m.group(1)}")
    for url in sorted(urls):
        rec = direct_download(url, out, session)
        if rec:
            manifest["files"].append(rec)
    manifest["status"] = "DOWNLOADED_PUBLIC" if manifest["files"] else "NO_PUBLIC_FILE"


def browser_context():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    return pw, browser, context


def adapter_ireland(candidate: dict, out: Path, manifest: dict):
    route = candidate.get("route") or {}
    resource = str(route.get("resource_id") or candidate.get("resource_id") or candidate.get("portal_ref") or "").strip()
    if not resource:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return
    pw, browser, context = browser_context()
    page = context.new_page()
    try:
        url = f"https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId={resource}"
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(400)
        (out / "portal_page.txt").write_text(page.locator("body").inner_text(timeout=15000), encoding="utf-8")
        got = False
        try:
            with page.expect_popup(timeout=7000) as popup_info:
                page.get_by_role("button", name=re.compile("Download Zip file", re.I)).click()
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded", timeout=20000)
            try:
                with page.expect_download(timeout=30000) as dl_info:
                    popup.get_by_role("button", name=re.compile("Proceed without association", re.I)).click(force=True)
                manifest["files"].append(persist_download(out, dl_info.value, popup.url))
                got = True
            finally:
                try:
                    popup.close()
                except Exception:
                    pass
        except Exception:
            pass
        if not got:
            endpoint = f"https://www.etenders.gov.ie/epps/cft/downloadCftResourceItems.do?resourceId={resource}&resourceType=ContractDocument&isContract=null"
            try:
                with page.expect_download(timeout=30000) as dl_info:
                    page.evaluate("u => window.location.href = u", endpoint)
                manifest["files"].append(persist_download(out, dl_info.value, endpoint))
                got = True
            except Exception as exc:
                manifest["error"] = repr(exc)
        manifest["status"] = "DOWNLOADED_PUBLIC" if got else "NO_PUBLIC_FILE"
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
    finally:
        try:
            page.close()
        except Exception:
            pass
        browser.close()
        pw.stop()


def prado_download(candidate: dict, out: Path, manifest: dict, default_detail: str | None = None):
    route = candidate.get("route") or {}
    documents_url = route.get("documents_url") or candidate.get("documents_url")
    detail_url = route.get("detail_url") or candidate.get("notice_url") or default_detail
    pw, browser, context = browser_context()
    page = context.new_page()
    try:
        if documents_url:
            page.goto(documents_url, wait_until="domcontentloaded", timeout=45000)
        elif detail_url:
            page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(300)
            try:
                page.get_by_role("link", name=re.compile("Dossier de consultation|documents", re.I)).click(timeout=6000)
                page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
        else:
            manifest["status"] = "ROUTE_INCOMPLETE"
            return
        page.wait_for_timeout(350)
        for iid in [
            "ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_choixAnonyme",
            "ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions",
        ]:
            try:
                page.evaluate(
                    "id => { const e=document.getElementById(id); if(e){ e.checked=true; e.dispatchEvent(new Event('change',{bubbles:true})); e.dispatchEvent(new Event('click',{bubbles:true})); }}",
                    iid,
                )
            except Exception:
                pass
        got = False
        validate = page.locator("#ctl0_CONTENU_PAGE_validateButton")
        if validate.count():
            try:
                with page.expect_download(timeout=7000) as dl_info:
                    validate.click(force=True)
                manifest["files"].append(persist_download(out, dl_info.value, page.url))
                got = True
            except Exception:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(700)
        if not got:
            full = page.locator("#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload")
            if full.count():
                try:
                    with page.expect_download(timeout=30000) as dl_info:
                        full.click(force=True)
                    manifest["files"].append(persist_download(out, dl_info.value, page.url))
                    got = True
                except Exception as exc:
                    manifest["error"] = repr(exc)
        body = ""
        try:
            body = page.locator("body").inner_text(timeout=10000)
            (out / "portal_page.txt").write_text(body, encoding="utf-8")
        except Exception:
            pass
        if got:
            manifest["status"] = "DOWNLOADED_PUBLIC"
        elif re.search(r"captcha|code de sécurité|security code", body, re.I):
            manifest["status"] = "CAPTCHA_REQUIRED"
        elif re.search(r"connexion|login|se connecter|identifier", body, re.I):
            manifest["status"] = "AUTH_REQUIRED"
        else:
            manifest["status"] = "NO_PUBLIC_FILE"
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
    finally:
        try:
            page.close()
        except Exception:
            pass
        browser.close()
        pw.stop()


def adapter_place(candidate: dict, out: Path, manifest: dict):
    route = candidate.get("route") or {}
    consultation_id = str(route.get("consultation_id") or candidate.get("consultation_id") or "").strip()
    org = str(route.get("org_acronym") or candidate.get("org_acronym") or "").strip()
    default = None
    if consultation_id:
        default = f"https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/{consultation_id}"
        if org:
            default += f"?orgAcronyme={org}"
    prado_download(candidate, out, manifest, default)


def adapter_lux(candidate: dict, out: Path, manifest: dict):
    prado_download(candidate, out, manifest, candidate.get("notice_url"))


def adapter_pcs(candidate: dict, out: Path, manifest: dict):
    notice_url = candidate.get("notice_url")
    if not notice_url:
        notice_ref = (candidate.get("route") or {}).get("notice_ref") or candidate.get("notice_ref")
        if notice_ref:
            notice_url = f"https://www.publiccontractsscotland.gov.uk/search/show/search_view.aspx?ID={notice_ref}"
    if not notice_url:
        manifest["status"] = "ROUTE_INCOMPLETE"
        return
    pw, browser, context = browser_context()
    page = context.new_page()
    try:
        page.goto(notice_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(400)
        body = page.locator("body").inner_text(timeout=12000)
        (out / "portal_page.txt").write_text(body, encoding="utf-8")
        try:
            with page.expect_download(timeout=25000) as dl_info:
                page.evaluate("() => __doPostBack('ctl00$ContentPlaceHolder1$notice_add_docs1$lnkZip','')")
            manifest["files"].append(persist_download(out, dl_info.value, notice_url))
            manifest["status"] = "DOWNLOADED_PUBLIC"
        except Exception as exc:
            if re.search(r"record(?:ing)? (?:your )?interest|register interest", body, re.I):
                manifest["status"] = "INTEREST_RECORDING_REQUIRED"
            elif re.search(r"login|sign in|log in", body, re.I):
                manifest["status"] = "AUTH_REQUIRED"
            else:
                manifest["status"] = "PUBLIC_POSTBACK_NO_DOWNLOAD"
            manifest["error"] = repr(exc)
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
    finally:
        try:
            page.close()
        except Exception:
            pass
        browser.close()
        pw.stop()


ADAPTERS = {
    "DIRECT_HTTP": adapter_direct,
    "UK_CONTRACTS_FINDER": adapter_direct,
    "UNGM": adapter_ungm,
    "IRELAND_ETENDERS": adapter_ireland,
    "FR_PLACE": adapter_place,
    "LUX_PMP": adapter_lux,
    "SCOTLAND_PCS": adapter_pcs,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--line", type=int, required=True)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    candidate = load_candidate(Path(args.queue), args.line)
    cid = str(candidate.get("candidate_id") or f"line-{args.line}")
    portal = str(candidate.get("portal") or candidate.get("portal_key") or candidate.get("source") or "").upper()
    root = Path(args.out) / slugify(cid)
    files_dir = root / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "candidate": candidate,
        "candidate_id": cid,
        "portal": portal,
        "queue_line": args.line,
        "status": "STARTED",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "files": [],
        "error": None,
    }
    (root / "candidate.json").write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        adapter = ADAPTERS.get(portal)
        if not adapter:
            manifest["status"] = "ADAPTER_PENDING"
        else:
            adapter(candidate, files_dir, manifest)
    except Exception as exc:
        manifest["status"] = "ERROR_RETRYABLE"
        manifest["error"] = repr(exc)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"candidate_id": cid, "portal": portal, "status": manifest["status"], "files": len(manifest["files"]), "root": str(root)}, indent=2))


if __name__ == "__main__":
    main()
