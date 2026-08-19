from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright
from pipeline.discover_uk_pcs_current import URL, clean, select_current_opportunities, submit_search

PAGE_TARGET = "ctl00$maincontent$PagingHelperTop$ddPageSelect"
PAGE_BOTTOM = "ctl00$maincontent$PagingHelperBottom$ddPageSelect"


def page_markers(html: str):
    text = clean(re.sub(r"<[^>]+>", " ", html))
    m = re.search(r"Showing\s+page\s+(\d+)\s+of\s+(\d+)", text, re.I)
    refs = re.findall(r"Reference\s*No:\s*([^\s<]+)", text, re.I)
    total = re.search(r"total\s+([\d,]+)\s+items", text, re.I)
    return {
        "page": int(m.group(1)) if m else None,
        "total_pages": int(m.group(2)) if m else None,
        "total_items": int(total.group(1).replace(',', '')) if total else None,
        "refs": refs[:30],
    }


async def main():
    out = {"schema": "PCS_DIRECT_ASPNET_POST_PROBE_V1", "generated_at": datetime.now(timezone.utc).isoformat(), "errors": []}
    async with async_playwright() as pw:
        chrome = os.getenv("CHROME_BIN") or None
        browser = await pw.chromium.launch(headless=True, executable_path=chrome)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        try:
            resp = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            out["landing_status"] = resp.status if resp else None
            telemetry, errors = {}, []
            if not await select_current_opportunities(page, telemetry, errors):
                out["errors"].extend(errors or [{"type": "FILTER_FAILED"}])
            else:
                await submit_search(page, telemetry)
                await page.wait_for_timeout(700)
                out["search_telemetry"] = telemetry
                html1 = await page.content()
                out["page1"] = page_markers(html1)
                form = await page.locator("#aspnetForm").evaluate("""form => {
                  const data = {};
                  for (const el of Array.from(form.elements || [])) {
                    if (!el.name || el.disabled) continue;
                    const tag = (el.tagName || '').toLowerCase();
                    const type = (el.type || '').toLowerCase();
                    if ((type === 'checkbox' || type === 'radio') && !el.checked) continue;
                    if (tag === 'select' && el.multiple) {
                      data[el.name] = Array.from(el.selectedOptions || [], o => o.value);
                    } else {
                      data[el.name] = el.value ?? '';
                    }
                  }
                  return data;
                }""")
                out["form_field_count"] = len(form)
                out["viewstate_len"] = len(str(form.get("__VIEWSTATE") or ""))
                out["eventvalidation_len"] = len(str(form.get("__EVENTVALIDATION") or ""))
                form["__EVENTTARGET"] = PAGE_TARGET
                form["__EVENTARGUMENT"] = ""
                form[PAGE_TARGET] = "2"
                # Browser native behavior leaves the other pager at its previous value.
                out["page2_post_relevant"] = {k: form.get(k) for k in ("__EVENTTARGET","__EVENTARGUMENT",PAGE_TARGET,PAGE_BOTTOM,"ctl00$maincontent$ddDocType","ctl00$maincontent$ddLocation")}
                r2 = await context.request.post(URL, form=form, timeout=90000)
                out["page2_status"] = r2.status
                out["page2_content_type"] = r2.headers.get("content-type")
                html2 = await r2.text()
                out["page2_bytes"] = len(html2.encode("utf-8", errors="ignore"))
                out["page2"] = page_markers(html2)
                out["page2_prefix"] = html2[:500]
        except Exception as exc:
            out["errors"].append({"type": "PROBE_ERROR", "error": repr(exc)})
        finally:
            await browser.close()

    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_direct_post_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
