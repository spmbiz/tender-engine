from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.discover_uk_pcs_current as base


async def page_number(page):
    body = base.clean(await page.locator("body").inner_text())
    match = re.search(r"Showing\s+page\s+(\d+)\s+of", body, re.I)
    return int(match.group(1)) if match else None


async def advance_v9(page, next_page, before_signature):
    selector, _, _ = await base.find_page_select(page)
    if selector is None:
        return False
    try:
        # Set the exact option value without dispatching change, then perform
        # exactly one WebForms postback while navigation is already awaited.
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            fired = await selector.evaluate("""(el, nextPage) => {
              const target = el.name || el.id || '';
              if (!target || typeof window.__doPostBack !== 'function') return false;
              el.value = String(nextPage);
              window.__doPostBack(target, '');
              return true;
            }""", next_page)
        if not fired:
            return False
        await page.wait_for_timeout(base.PAGE_WAIT_MS)
        return await page_number(page) == next_page
    except Exception:
        return False


base.advance = advance_v9
base.MAX_PAGES = 5
base.PAGE_WAIT_MS = 300

if __name__ == "__main__":
    asyncio.run(base.main())
