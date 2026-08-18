from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


INTEREST_RE = re.compile(r"api|download|file|document|export|tender|procedure|public|today|attachment|requirement|version", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://app.eop.bg/today/597088")
    ap.add_argument("--out", default="bg-eop-probe.json")
    args = ap.parse_args()

    chrome = os.getenv("CHROME_BIN") or None
    responses = []
    json_bodies = []
    console = []

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
                row = {
                    "url": str(resp.url),
                    "status": int(resp.status),
                    "resource_type": str(req.resource_type),
                    "method": str(req.method),
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
            controls = page.locator("button, [role='button']").evaluate_all(
                "els => els.map(e => ({text:(e.innerText||e.textContent||'').trim(), aria:e.getAttribute('aria-label')||'', title:e.getAttribute('title')||''})).filter(x => x.text||x.aria||x.title)"
            )
        except Exception:
            pass

        performance_urls = []
        try:
            performance_urls = page.evaluate("performance.getEntriesByType('resource').map(x => x.name)") or []
        except Exception:
            pass

        storage = {}
        for name, expr in {
            "localStorage": "Object.fromEntries(Object.entries(localStorage))",
            "sessionStorage": "Object.fromEntries(Object.entries(sessionStorage))",
        }.items():
            try:
                storage[name] = page.evaluate(expr)
            except Exception as exc:
                storage[name] = {"error": repr(exc)}

        scripts = []
        try:
            scripts = page.locator("script[src]").evaluate_all("els => els.map(e => e.src).filter(Boolean)")
        except Exception:
            pass

        result = {
            "url": args.url,
            "resolved_url": page.url,
            "body_text": body[:500_000],
            "anchors": anchors[:1000],
            "controls": controls[:1000],
            "responses": responses[:5000],
            "json_bodies": json_bodies[:1000],
            "performance_urls": performance_urls[:5000],
            "storage": storage,
            "scripts": scripts[:500],
            "console": console[:500],
        }
        browser.close()

    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    interesting = []
    seen = set()
    for row in responses:
        url = row.get("url") or ""
        key = (url, row.get("status"), row.get("resource_type"))
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
        "interesting": interesting[:300],
        "scripts": scripts[:80],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
