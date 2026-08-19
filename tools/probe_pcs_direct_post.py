from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

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
    out = {"schema": "PCS_DIRECT_ASPNET_POST_PROBE_V2_INDEPENDENT_JUMPS", "generated_at": datetime.now(timezone.utc).isoformat(), "errors": []}
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
                browser_html = await page.content()
                out["browser_grid_before_direct_posts"] = page_markers(browser_html)
                base_form = await page.locator("#aspnetForm").evaluate("""form => {
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
                out["form_field_count"] = len(base_form)
                out["viewstate_len"] = len(str(base_form.get("__VIEWSTATE") or ""))
                out["eventvalidation_len"] = len(str(base_form.get("__EVENTVALIDATION") or ""))
                out["base_relevant"] = {k: base_form.get(k) for k in ("__EVENTTARGET","__EVENTARGUMENT",PAGE_TARGET,PAGE_BOTTOM,"ctl00$maincontent$ddDocType","ctl00$maincontent$ddLocation")}

                jumps = []
                for wanted in (1, 2, 3):
                    form = copy.deepcopy(base_form)
                    form["__EVENTTARGET"] = PAGE_TARGET
                    form["__EVENTARGUMENT"] = ""
                    form[PAGE_TARGET] = str(wanted)
                    r = await context.request.post(URL, form=form, timeout=90000)
                    html = await r.text()
                    jumps.append({
                        "requested_page": wanted,
                        "status": r.status,
                        "content_type": r.headers.get("content-type"),
                        "bytes": len(html.encode("utf-8", errors="ignore")),
                        "markers": page_markers(html),
                    })
                out["independent_jumps"] = jumps
                page_sets = [set((x.get("markers") or {}).get("refs") or []) for x in jumps]
                out["independent_jump_proven"] = (
                    [x.get("markers", {}).get("page") for x in jumps] == [1, 2, 3]
                    and len({x.get("markers", {}).get("total_pages") for x in jumps}) == 1
                    and all(page_sets[i].isdisjoint(page_sets[j]) for i in range(len(page_sets)) for j in range(i+1, len(page_sets)))
                )
        except Exception as exc:
            out["errors"].append({"type": "PROBE_ERROR", "error": repr(exc)})
        finally:
            await browser.close()

    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_direct_post_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
