from pathlib import Path

p=Path('pipeline/discover_uk_pcs_current.py')
text=p.read_text(encoding='utf-8')
old='''            # Some PCS renders do not wire the page select's change event in a
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
'''
new='''            # The real PCS pager select already owns an inline onchange which
            # calls __doPostBack. Arm the navigation waiter BEFORE select_option
            # so the native postback can complete without racing a second submit.
            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    await selector.select_option(label=label)
                await page.wait_for_timeout(PAGE_WAIT_MS)
                body = clean(await page.locator("body").inner_text())
                match = re.search(r"Showing\\s+page\\s+(\\d+)\\s+of", body, re.I)
                if match and int(match.group(1)) == next_page:
                    return True
            except Exception:
                pass

            # Fallback for a render where select_option did not fire onchange:
            # reacquire the pager and perform the exact public ASP.NET postback
            # once, again with navigation armed before the synchronous call.
            try:
                selector, _, labels = await find_page_select(page)
                if selector is None:
                    return False
                body = clean(await page.locator("body").inner_text())
                match = re.search(r"Showing\\s+page\\s+(\\d+)\\s+of", body, re.I)
                if match and int(match.group(1)) == next_page:
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
                await page.wait_for_timeout(PAGE_WAIT_MS)
                body = clean(await page.locator("body").inner_text())
                match = re.search(r"Showing\\s+page\\s+(\\d+)\\s+of", body, re.I)
                if match and int(match.group(1)) == next_page:
                    return True
            except Exception:
                return False
'''
if old not in text:
    raise SystemExit('PCS V8 anchor missing')
if text.count(old)!=1:
    raise SystemExit('PCS V8 anchor not unique')
text=text.replace(old,new,1)
text=text.replace('PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER','PCS_CURRENT_OPPORTUNITIES_BROWSER_V8_NATIVE_ONCHANGE')
p.write_text(text,encoding='utf-8')
print('PCS V8 native onchange pager patch applied')
