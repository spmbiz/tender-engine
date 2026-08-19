from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright
from pipeline.discover_uk_pcs_current import URL, clean, select_current_opportunities, submit_search, find_page_select


async def page_number(page):
    body = clean(await page.locator("body").inner_text())
    m = re.search(r"Showing\s+page\s+(\d+)\s+of\s+(\d+)", body, re.I)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


async def main():
    out = {
        "schema": "PCS_PAGE2_NATIVE_POST_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "requests": [],
        "errors": [],
    }
    async with async_playwright() as pw:
        chrome = os.getenv("CHROME_BIN") or None
        browser = await pw.chromium.launch(headless=True, executable_path=chrome)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            resp = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            out["http_status"] = resp.status if resp else None
            telemetry, errors = {}, []
            if not await select_current_opportunities(page, telemetry, errors):
                out["errors"].extend(errors or [{"type": "FILTER_FAILED"}])
            else:
                await submit_search(page, telemetry)
                await page.wait_for_timeout(700)
                out["before_page"], out["total_pages"] = await page_number(page)
                selector, _, labels = await find_page_select(page)
                if selector is None:
                    out["errors"].append({"type": "PAGER_NOT_FOUND"})
                else:
                    out["pager_meta"] = await selector.evaluate("el => ({id:el.id||'',name:el.name||'',value:el.value||'',onchange:el.getAttribute('onchange')||''})")

                    def on_request(req):
                        try:
                            if req.method.upper() != "POST" or "Search_MainPage.aspx" not in req.url:
                                return
                            raw = req.post_data or ""
                            fields = parse_qs(raw, keep_blank_values=True)
                            relevant = {}
                            for key, vals in fields.items():
                                if key in {"__EVENTTARGET", "__EVENTARGUMENT"} or "PageSelect" in key or "ddDocType" in key or "ddLocation" in key:
                                    relevant[key] = vals[:5]
                            out["requests"].append({
                                "method": req.method,
                                "url": req.url,
                                "post_bytes": len(raw.encode("utf-8", errors="ignore")),
                                "field_count": len(fields),
                                "relevant_fields": relevant,
                                "has_viewstate": "__VIEWSTATE" in fields,
                                "viewstate_len": len((fields.get("__VIEWSTATE") or [""])[0]),
                                "eventvalidation_len": len((fields.get("__EVENTVALIDATION") or [""])[0]),
                            })
                        except Exception as exc:
                            out["errors"].append({"type": "REQUEST_CAPTURE_ERROR", "error": repr(exc)})

                    page.on("request", on_request)
                    try:
                        await selector.select_option(label=labels.get(2, "Page 2"))
                    except Exception as exc:
                        out["errors"].append({"type": "SELECT_PAGE2_ERROR", "error": repr(exc)})
                    await page.wait_for_timeout(5000)
                    out["after_page"], out["after_total_pages"] = await page_number(page)
                    out["after_url"] = page.url
                    out["body_tail"] = clean(await page.locator("body").inner_text())[-3000:]
        except Exception as exc:
            out["errors"].append({"type": "PROBE_ERROR", "error": repr(exc)})
        finally:
            await browser.close()

    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_page2_post_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
