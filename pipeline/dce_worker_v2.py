from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

import dce_worker as base
from ted_resolver import resolve_ted_candidate


def optimized_browser_context():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    launch_kwargs = {"headless": True}
    chrome_bin = os.getenv("CHROME_BIN", "").strip()
    if chrome_bin and Path(chrome_bin).exists():
        launch_kwargs["executable_path"] = chrome_bin
    browser = pw.chromium.launch(**launch_kwargs)
    context = browser.new_context(accept_downloads=True)
    return pw, browser, context


def optimized_ungm(candidate: dict, out: Path, manifest: dict):
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/2.0 public procurement research"})
    route = candidate.get("route") or {}
    notice_id = str(route.get("notice_id") or candidate.get("notice_id") or "").strip()
    notice_url = candidate.get("notice_url") or (f"https://www.ungm.org/Public/Notice/{notice_id}" if notice_id else None)
    if notice_url and not notice_id:
        m = re.search(r"/Notice/(\d+)", notice_url, re.I)
        notice_id = m.group(1) if m else ""
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
    for u in re.findall(r"href=[\"']([^\"']*DownloadDocument[^\"']+)", text, re.I):
        urls.add(urljoin(notice_url, u.replace("&amp;", "&")))
    for u in re.findall(r"https?://[^\s\"'<>]+DownloadDocument[^\s\"'<>]+", text, re.I):
        urls.add(u.replace("&amp;", "&"))
    if notice_id:
        for m in re.finditer(r"documentId=([A-Za-z0-9_-]+)", text):
            urls.add(f"https://www.ungm.org/Public/Notice/DownloadDocument?noticeId={notice_id}&documentId={m.group(1)}")
    for url in sorted(urls):
        rec = base.direct_download(url, out, session)
        if rec:
            manifest["files"].append(rec)
    manifest["status"] = "DOWNLOADED_PUBLIC" if manifest["files"] else "NO_PUBLIC_FILE"


base.browser_context = optimized_browser_context
base.ADAPTERS["UNGM"] = optimized_ungm


def run_ted(candidate: dict, files_dir: Path, manifest: dict, root: Path):
    resolution = resolve_ted_candidate(candidate)
    (root / "ted_resolution.json").write_text(json.dumps(resolution, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["ted_resolution"] = {
        "publication_number": resolution.get("publication_number"),
        "xml_url_used": resolution.get("xml_url_used"),
        "downstream_count": len(resolution.get("downstream") or []),
        "error": resolution.get("error"),
    }
    downstream = resolution.get("downstream") or []
    if not downstream:
        manifest["status"] = "TED_ROUTE_UNRESOLVED"
        manifest["error"] = resolution.get("error")
        return

    attempts = []
    unsupported = []
    for idx, item in enumerate(downstream[:8], start=1):
        portal = item.get("portal")
        url = item.get("url")
        route = item.get("route") or {}
        if not portal or portal not in base.ADAPTERS:
            unsupported.append(item)
            continue
        sub = dict(candidate)
        sub["portal"] = portal
        sub["source"] = portal
        sub["notice_url"] = url
        sub["route"] = route
        if portal == "DIRECT_HTTP":
            sub["documents"] = [{"url": url}]
            sub["route"] = {"document_urls": [url]}
        before = len(manifest["files"])
        old_status = manifest.get("status")
        old_error = manifest.get("error")
        try:
            base.ADAPTERS[portal](sub, files_dir, manifest)
            attempts.append({"index": idx, "portal": portal, "url": url, "route": route, "status": manifest.get("status"), "files_added": len(manifest["files"]) - before, "error": manifest.get("error")})
        except Exception as exc:
            attempts.append({"index": idx, "portal": portal, "url": url, "route": route, "status": "ERROR_RETRYABLE", "files_added": 0, "error": repr(exc)})
            manifest["status"] = old_status
            manifest["error"] = old_error
        if len(manifest["files"]) > before:
            manifest["status"] = "DOWNLOADED_PUBLIC"
            break

    manifest["ted_downstream_attempts"] = attempts
    manifest["ted_unsupported_routes"] = unsupported
    if manifest["files"]:
        manifest["status"] = "DOWNLOADED_PUBLIC"
    elif attempts:
        statuses = [a.get("status") for a in attempts if a.get("status")]
        priority = ["CAPTCHA_REQUIRED", "AUTH_REQUIRED", "INTEREST_RECORDING_REQUIRED", "PUBLIC_POSTBACK_NO_DOWNLOAD", "NO_PUBLIC_FILE", "DOWNSTREAM_PORTAL_OR_NO_PUBLIC_FILE", "ERROR_RETRYABLE"]
        manifest["status"] = next((s for s in priority if s in statuses), statuses[-1] if statuses else "TED_DCE_NOT_DOWNLOADED")
    else:
        manifest["status"] = "TED_DOWNSTREAM_ADAPTER_PENDING"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--line", type=int, required=True)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    candidate = base.load_candidate(Path(args.queue), args.line)
    cid = str(candidate.get("candidate_id") or f"line-{args.line}")
    portal = str(candidate.get("portal") or candidate.get("portal_key") or candidate.get("source") or "").upper()
    root = Path(args.out) / base.slugify(cid)
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
        "chrome_bin": os.getenv("CHROME_BIN") or None,
    }
    (root / "candidate.json").write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        if portal == "TED":
            run_ted(candidate, files_dir, manifest, root)
        else:
            adapter = base.ADAPTERS.get(portal)
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
