from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


INTEREST_RE = re.compile(r"api|download|file|document|export|tender|procedure|public|today|attachment|requirement|version|signed", re.I)
SERVICE_JS = "https://service.eop.bg/NX1Service.svc/js"
SERVICE_METHOD_RE = re.compile(
    r"(?:GetPublishedTenderExportsByTenderId|GetPublishedTenderDetails|GetDocument|DownloadDocument|"
    r"GetSigned|SignedUrl|Download|DocumentById|GetPublicTenderRequirements|RequirementBox)",
    re.I,
)


def _safe_headers(headers: dict) -> dict:
    # Public request metadata only. Never persist auth/session secrets if a portal
    # later adds them; they are irrelevant to the anonymous adapter contract.
    keep = {"content-type", "accept", "origin", "referer", "x-requested-with"}
    return {str(k): str(v)[:1000] for k, v in (headers or {}).items() if str(k).casefold() in keep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://app.eop.bg/today/597088")
    ap.add_argument("--out", default="bg-eop-probe.json")
    args = ap.parse_args()

    chrome = os.getenv("CHROME_BIN") or None
    responses = []
    json_bodies = []
    console = []

    service_js = ""
    try:
        rr = requests.get(SERVICE_JS, timeout=30, headers={"User-Agent": "Tender-Engine/EOP-Probe"})
        if rr.ok:
            service_js = rr.text[:8_000_000]
    except Exception:
        service_js = ""

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chrome, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(ignore_https_errors=False, locale="bg-BG")
        page = context.new_page()

        def on_console(msg):
            try:
                console.append({"type": msg.type, "text": msg.text[:1500]})
            except Exception:
                pass

        def on_response(resp):
            try:
                req = resp.request
                headers = resp.headers or {}
                ct = str(headers.get("content-type") or "")
                post_data = None
                try:
                    post_data = req.post_data
                except Exception:
                    pass
                row = {
                    "url": str(resp.url),
                    "status": int(resp.status),
                    "resource_type": str(req.resource_type),
                    "method": str(req.method),
                    "request_post_data": (post_data[:100_000] if isinstance(post_data, str) else None),
                    "request_headers": _safe_headers(req.headers or {}),
                    "content_type": ct[:250],
                    "content_disposition": str(headers.get("content-disposition") or "")[:500],
                }
                responses.append(row)
                if ("json" in ct.casefold() or req.resource_type in {"xhr", "fetch"}) and resp.status < 500:
                    try:
                        body = resp.text()
                        if body and len(body) <= 1_500_000:
                            json_bodies.append({**row, "body": body[:1_500_000]})
                    except Exception as exc:
                        json_bodies.append({**row, "body_error": repr(exc)[:500]})
            except Exception:
                pass

        page.on("console", on_console)
        page.on("response", on_response)
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(1500)

        body = ""
        try:
            body = page.locator("body").inner_text(timeout=15000)
        except Exception:
            pass

        anchors = []
        try:
            anchors = page.locator("a[href]").evaluate_all(
                "els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim(), download:a.getAttribute('download')||''}))"
            )
        except Exception:
            pass

        controls = []
        try:
            controls = page.locator("button, [role='button'], a, [tabindex], [class*='download'], [class*='document']").evaluate_all(
                """els => els.map((e,index) => ({
                    index,
                    tag:e.tagName,
                    text:(e.innerText||e.textContent||'').trim(),
                    aria:e.getAttribute('aria-label')||'',
                    title:e.getAttribute('title')||'',
                    href:e.href||'',
                    cls:e.className||'',
                    data:Object.fromEntries(Array.from(e.attributes||[]).filter(a=>a.name.startsWith('data-')).map(a=>[a.name,a.value]))
                })).filter(x => x.text||x.aria||x.title||x.href)"""
            )
        except Exception:
            pass

        performance_urls = []
        try:
            performance_urls = page.evaluate("performance.getEntriesByType('resource').map(x => x.name)") or []
        except Exception:
            pass

        scripts = []
        try:
            scripts = page.locator("script[src]").evaluate_all("els => els.map(e => e.src).filter(Boolean)")
        except Exception:
            pass

        service_method_snippets = []
        if service_js:
            for m in SERVICE_METHOD_RE.finditer(service_js):
                a = max(0, m.start() - 700)
                b = min(len(service_js), m.end() + 1800)
                snippet = service_js[a:b]
                if snippet not in service_method_snippets:
                    service_method_snippets.append(snippet)
                if len(service_method_snippets) >= 100:
                    break

        result = {
            "url": args.url,
            "resolved_url": page.url,
            "body_text": body[:500_000],
            "anchors": anchors[:1500],
            "controls": controls[:2000],
            "responses": responses[:6000],
            "json_bodies": json_bodies[:1200],
            "performance_urls": performance_urls[:6000],
            "scripts": scripts[:500],
            "service_js_url": SERVICE_JS,
            "service_js_chars": len(service_js),
            "service_method_snippets": service_method_snippets,
            "console": console[:500],
        }
        browser.close()

    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    interesting = []
    seen = set()
    for row in responses:
        url = row.get("url") or ""
        key = (url, row.get("status"), row.get("resource_type"), row.get("request_post_data"))
        if key in seen:
            continue
        seen.add(key)
        if row.get("resource_type") in {"xhr", "fetch"} or INTEREST_RE.search(url):
            interesting.append(row)
    print(json.dumps({
        "resolved_url": result["resolved_url"],
        "body_chars": len(body),
        "responses": len(responses),
        "json_bodies": len(json_bodies),
        "anchors": len(anchors),
        "controls": len(controls),
        "service_js_chars": len(service_js),
        "interesting": interesting[:300],
        "service_method_snippets": service_method_snippets[:30],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
