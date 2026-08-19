from __future__ import annotations

import asyncio
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

from pipeline.discover_uk_pcs_current import URL, clean, current_option, select_current_opportunities, submit_search


async def main():
    out = {
        "schema": "PCS_ASPNET_PAGER_CONTRACT_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "errors": [],
    }
    async with async_playwright() as pw:
        chrome = os.getenv("CHROME_BIN") or None
        browser = await pw.chromium.launch(headless=True, executable_path=chrome)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            resp = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            out["http_status"] = resp.status if resp else None
            telemetry = {}
            errors = []
            if not await select_current_opportunities(page, telemetry, errors):
                out["errors"].extend(errors or [{"type": "FILTER_FAILED"}])
            else:
                await submit_search(page, telemetry)
                await page.wait_for_timeout(600)
                out["search_telemetry"] = telemetry
                body = clean(await page.locator("body").inner_text())
                m = re.search(r"Showing\s+page\s+(\d+)\s+of\s+(\d+)", body, re.I)
                if m:
                    out["showing_page"] = int(m.group(1)); out["total_pages"] = int(m.group(2))
                selects = page.locator("select")
                candidates = []
                for idx in range(await selects.count()):
                    sel = selects.nth(idx)
                    meta = await sel.evaluate("""el => ({
                      index:Array.from(document.querySelectorAll('select')).indexOf(el),
                      id:el.id||'', name:el.name||'', onchange:el.getAttribute('onchange')||'',
                      value:el.value||'', selectedIndex:el.selectedIndex,
                      options:Array.from(el.options||[]).slice(0,5).map(o=>({text:(o.textContent||'').trim(),value:o.value,selected:o.selected})),
                      optionCount:(el.options||[]).length,
                      formId:el.form?.id||'', formAction:el.form?.action||'', formMethod:el.form?.method||''
                    })""")
                    if int(meta.get("optionCount") or 0) >= 2:
                        candidates.append(meta)
                pager = None
                for meta in candidates:
                    opts = meta.get("options") or []
                    if any(re.fullmatch(r"Page\s*1", str(o.get("text") or ""), re.I) for o in opts) and int(meta.get("optionCount") or 0) > 100:
                        pager = meta; break
                out["selects"] = candidates
                out["pager"] = pager
                hidden = await page.locator("input[type=hidden]").evaluate_all("""els => els.map(el => ({name:el.name||'',id:el.id||'',value:(el.value||'').slice(0,300),valueLength:(el.value||'').length})).filter(x => ['__EVENTTARGET','__EVENTARGUMENT','__VIEWSTATE','__VIEWSTATEGENERATOR','__EVENTVALIDATION'].includes(x.name||x.id))""")
                out["aspnet_hidden"] = hidden
                out["do_postback_type"] = await page.evaluate("typeof window.__doPostBack")
        except Exception as exc:
            out["errors"].append({"type": "PROBE_ERROR", "error": repr(exc)})
        finally:
            await browser.close()

    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_pager_contract_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
