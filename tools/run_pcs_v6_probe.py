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


async def advance_v8(page, next_page, before_signature):
    selector, _, labels = await base.find_page_select(page)
    if selector is None:
        return False
    label = labels.get(next_page, f"Page {next_page}")

    # The real PCS pager select has an inline onchange which calls
    # __doPostBack. Arm the navigation waiter BEFORE select_option so we do not
    # race the native postback with a second synthetic submit/postback.
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            await selector.select_option(label=label)
        await page.wait_for_timeout(base.PAGE_WAIT_MS)
        if await page_number(page) == next_page:
            return True
    except Exception:
        pass

    # If a render did not fire the inline change handler, reacquire the pager
    # and reproduce the exact public ASP.NET event once, with navigation armed.
    try:
        selector, _, labels = await base.find_page_select(page)
        if selector is None:
            return False
        if await page_number(page) == next_page:
            return True
        await selector.select_option(label=labels.get(next_page, f"Page {next_page}"))
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            fired = await selector.evaluate("""el => {
              const target = el.name || el.id || '';
              if (!target || typeof window.__doPostBack !== 'function') return false;
              window.__doPostBack(target, '');
              return true;
            }""")
        if not fired:
            return False
        await page.wait_for_timeout(base.PAGE_WAIT_MS)
        return await page_number(page) == next_page
    except Exception:
        return False


base.advance = advance_v8
base.MAX_PAGES = 5
base.PAGE_WAIT_MS = 300

if __name__ == "__main__":
    asyncio.run(base.main())
