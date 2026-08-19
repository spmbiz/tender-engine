from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

URLS = [
    "https://pubblicitalegale.anticorruzione.it/bandi",
    "https://pubblicitalegale.anticorruzione.it/ricerca-generica",
]


async def main():
    captured = []
    pages = []
    async with async_playwright() as pw:
        chrome = os.getenv("CHROME_BIN") or None
        browser = await pw.chromium.launch(headless=True, executable_path=chrome)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()

        async def on_response(resp):
            try:
                req = resp.request
                rt = req.resource_type
                ctype = (resp.headers or {}).get("content-type", "")
                url = resp.url
                if rt in {"xhr", "fetch"} or "json" in ctype.lower() or any(x in url.lower() for x in ("api", "search", "ricerca", "bandi", "avvisi")):
                    item = {
                        "url": url,
                        "status": resp.status,
                        "resource_type": rt,
                        "content_type": ctype,
                        "method": req.method,
                        "post_data": (req.post_data or "")[:5000],
                    }
                    if "/api/v0/avvisi" in url and resp.status == 200:
                        try:
                            body = await resp.text()
                            item["body_sample"] = body[:50000]
                        except Exception as exc:
                            item["body_sample_error"] = repr(exc)
                    captured.append(item)
            except Exception:
                pass

        page.on("response", on_response)
        for url in URLS:
            err = None
            status = None
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
                status = resp.status if resp else None
                await page.wait_for_timeout(8000)
            except Exception as exc:
                err = repr(exc)
            try:
                html = await page.content()
                title = await page.title()
                body = (await page.locator("body").inner_text())[:12000]
            except Exception:
                html, title, body = "", "", ""
            pages.append({
                "url": url,
                "status": status,
                "error": err,
                "title": title,
                "html_bytes": len(html.encode("utf-8", errors="ignore")),
                "body_sample": body,
            })
        await browser.close()

    out = {
        "schema": "ANAC_PVL_PUBLIC_NETWORK_PROBE_V3_API_BODY_SAMPLE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chrome": chrome,
        "pages": pages,
        "responses": captured[:500],
    }
    Path("control").mkdir(exist_ok=True)
    Path("control/anac_pvl_network_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
