from pathlib import Path

p = Path('pipeline/discover_uk_pcs_current.py')
text = p.read_text(encoding='utf-8')

old_search = '''                await node.click(timeout=5000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["search_submitted"] = "CONTROL_CLICK"
                telemetry["search_control"] = meta
                return True
'''
new_search = '''                # Search Notices is an ASP.NET postback link. Arm navigation
                # before clicking; otherwise we can read the old All Notices
                # grid while the Current Opportunity postback is still starting.
                try:
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
                        await node.click(timeout=5000)
                    telemetry["search_navigation_proven"] = True
                except Exception as exc:
                    telemetry["search_navigation_proven"] = False
                    telemetry["search_navigation_error"] = repr(exc)
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["search_submitted"] = "CONTROL_CLICK_NAV_SAFE"
                telemetry["search_control"] = meta
                return True
'''

old_advance = '''    selector, _, labels = await find_page_select(page)
    if selector is not None:
        try:
            label = labels.get(next_page, f"Page {next_page}")
            await selector.select_option(label=label)
            await page.wait_for_timeout(350)
            body = clean(await page.locator("body").inner_text())
            match = re.search(r"Showing\\s+page\\s+(\\d+)\\s+of", body, re.I)
            if match and int(match.group(1)) == next_page:
                await page.wait_for_timeout(PAGE_WAIT_MS)
                return True

            # Some PCS renders do not wire the page select's change event in a
            # way Playwright triggers. Submit the same public ASP.NET form with
            # the selected Page N value; the next loop verifies Reference-No
            # signature, so an ineffective submit is caught rather than trusted.
            fired = await selector.evaluate("""el => {
              const form = el.form;
              if (!form) return false;
              setTimeout(() => form.submit(), 0);
              return true;
            }""")
            if fired:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(PAGE_WAIT_MS)
                return True
        except Exception:
            pass
'''
new_advance = '''    selector, _, labels = await find_page_select(page)
    if selector is not None:
        try:
            # Exact PCS/WebForms pager contract: set Page N without dispatching
            # a second change event, then perform one __doPostBack while the
            # navigation waiter is already armed. This is the same POST proven
            # by the public form probe (EVENTTARGET = top pager select).
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
            await page.wait_for_timeout(PAGE_WAIT_MS)
            body = clean(await page.locator("body").inner_text())
            match = re.search(r"Showing\\s+page\\s+(\\d+)\\s+of", body, re.I)
            if match and int(match.group(1)) == next_page:
                return True
        except Exception:
            pass
'''

for old, new, label in ((old_search, new_search, 'search'), (old_advance, new_advance, 'advance')):
    if old not in text:
        raise SystemExit(f'PCS V10 anchor missing: {label}')
    if text.count(old) != 1:
        raise SystemExit(f'PCS V10 anchor not unique: {label}')
    text = text.replace(old, new, 1)

text = text.replace('PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER', 'PCS_CURRENT_OPPORTUNITIES_BROWSER_V10_NAV_SAFE_SEARCH_POSTBACK')
p.write_text(text, encoding='utf-8')
print('PCS V10 nav-safe search + exact pager postback patch applied')
