from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.discover_uk_pcs_current as base


async def advance_v7(page, next_page, before_signature):
    selector, _, labels = await base.find_page_select(page)
    if selector is not None:
        try:
            label = labels.get(next_page, f"Page {next_page}")
            await selector.select_option(label=label)
            await page.wait_for_timeout(150)
            body = base.clean(await page.locator("body").inner_text())
            match = re.search(r"Showing\s+page\s+(\d+)\s+of", body, re.I)
            if match and int(match.group(1)) == next_page:
                await page.wait_for_timeout(base.PAGE_WAIT_MS)
                return True

            meta = await selector.evaluate("""el => ({
              name:el.name||'', id:el.id||'', onchange:el.getAttribute('onchange')||'',
              value:el.value||'', formId:el.form?.id||''
            })""")
            target = meta.get("name") or meta.get("id") or ""
            if target:
                try:
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
                        fired = await selector.evaluate("""el => {
                          const target = el.name || el.id || '';
                          if (!target || typeof window.__doPostBack !== 'function') return false;
                          window.__doPostBack(target, '');
                          return true;
                        }""")
                    if not fired:
                        return False
                except Exception:
                    return False
                await page.wait_for_timeout(base.PAGE_WAIT_MS)
                body = base.clean(await page.locator("body").inner_text())
                match = re.search(r"Showing\s+page\s+(\d+)\s+of", body, re.I)
                if match and int(match.group(1)) == next_page:
                    return True
        except Exception:
            pass
    return False


base.advance = advance_v7
base.MAX_PAGES = 5
base.PAGE_WAIT_MS = 300

if __name__ == "__main__":
    asyncio.run(base.main())
