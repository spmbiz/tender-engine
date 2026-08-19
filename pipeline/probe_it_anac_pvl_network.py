from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

OUT = Path(os.getenv("IT_ANAC_PVL_PROBE_OUT", "control/it_anac_pvl_network_probe.json"))
START_URL = "https://pubblicitalegale.anticorruzione.it/bandi"
ALLOWED_HOST_SUFFIX = "anticorruzione.it"
MAX_BODY = 30000


def clean_url(url: str) -> str:
    return str(url or "").strip()


def safe_json_shape(value):
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(str(k) for k in value.keys())[:100],
            "sample": {str(k): safe_json_shape(v) for k, v in list(value.items())[:12]},
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "item_shape": safe_json_shape(value[0]) if value else None,
        }
    return {"type": type(value).__name__, "sample": str(value)[:300]}


async def main():
    captured = []
    console = []
    page_meta = {}
    errors = []
    seen = set()

    async with async_playwright() as pw:
        chrome = os.getenv("CHROME_BIN") or None
        browser = await pw.chromium.launch(headless=True, executable_path=chrome)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="it-IT",
            user_agent="Tender-Engine/7.1 (+public procurement research; ANAC PVL public endpoint discovery)",
        )
        page = await context.new_page()
        page.on("console", lambda msg: console.append({"type": msg.type, "text": msg.text[:2000]}))

        async def handle_response(response):
            try:
                url = clean_url(response.url)
                parsed = urlparse(url)
                if not parsed.hostname or not parsed.hostname.endswith(ALLOWED_HOST_SUFFIX):
                    return
                request = response.request
                rtype = request.resource_type
                ctype = (response.headers.get("content-type") or "").lower()
                interesting = rtype in {"xhr", "fetch"} or "json" in ctype or "/api/" in parsed.path.lower()
                if not interesting:
                    return
                key = (request.method, url, response.status)
                if key in seen:
                    return
                seen.add(key)
                item = {
                    "method": request.method,
                    "url": url,
                    "status": response.status,
                    "resource_type": rtype,
                    "content_type": ctype,
                    "request_post_data": (request.post_data or "")[:12000] or None,
                }
                try:
                    body = await response.body()
                    item["body_bytes"] = len(body)
                    item["body_sha256"] = hashlib.sha256(body).hexdigest()
                    if "json" in ctype or (body[:1] in (b"{", b"[")):
                        try:
                            value = json.loads(body.decode("utf-8", errors="strict"))
                            item["json_shape"] = safe_json_shape(value)
                            item["json_sample"] = value if len(body) <= MAX_BODY else None
                        except Exception as exc:
                            item["json_parse_error"] = repr(exc)
                            item["body_prefix"] = body[:3000].decode("utf-8", errors="replace")
                    else:
                        item["body_prefix"] = body[:3000].decode("utf-8", errors="replace")
                except Exception as exc:
                    item["body_error"] = repr(exc)
                captured.append(item)
            except Exception as exc:
                errors.append({"stage": "response_handler", "error": repr(exc)})

        page.on("response", handle_response)
        try:
            response = await page.goto(START_URL, wait_until="domcontentloaded", timeout=120000)
            page_meta["landing_status"] = response.status if response else None
            await page.wait_for_timeout(12000)
            page_meta["title"] = await page.title()
            page_meta["final_url"] = page.url
            page_meta["body_text_prefix"] = (await page.locator("body").inner_text())[:12000]
            page_meta["html_bytes"] = len((await page.content()).encode("utf-8"))

            # Scroll to force any lazy lists/network calls without interacting with
            # submission or authenticated functionality.
            for _ in range(4):
                await page.mouse.wheel(0, 1800)
                await page.wait_for_timeout(1200)

            # If a clearly labelled pagination control exists, click it once to
            # expose the list pagination contract. This is read-only public UI.
            candidates = page.get_by_role("button", name="Next")
            if await candidates.count() == 0:
                candidates = page.get_by_role("button", name="Successivo")
            if await candidates.count() > 0:
                try:
                    await candidates.first.click(timeout=5000)
                    await page.wait_for_timeout(5000)
                    page_meta["pagination_click"] = True
                except Exception as exc:
                    page_meta["pagination_click_error"] = repr(exc)
            else:
                page_meta["pagination_click"] = False
        except Exception as exc:
            errors.append({"stage": "navigation", "error": repr(exc)})
        finally:
            await page.wait_for_timeout(1000)
            await browser.close()

    payload = {
        "schema": "IT_ANAC_PVL_NETWORK_PROBE_V1",
        "start_url": START_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page": page_meta,
        "network": captured,
        "network_count": len(captured),
        "errors": errors,
        "console": console[-50:],
        "pass": bool(captured and not errors),
        "semantics": (
            "Read-only browser probe of the official public ANAC Legal Advertising platform. "
            "Only anticorruzione.it XHR/fetch/API-like responses are persisted; credentials are neither used nor requested. "
            "The purpose is endpoint/schema discovery before implementing a direct official JSON collector."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
