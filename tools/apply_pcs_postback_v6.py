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
new='''            # PCS is classic ASP.NET. A raw form.submit() loses the pager's
            # event target and can reset the result grid to an empty/default
            # state. Reproduce the page's own postback contract instead.
            fired = await selector.evaluate("""el => {
              const target = el.name || el.id || '';
              if (!target || typeof window.__doPostBack !== 'function') return false;
              setTimeout(() => window.__doPostBack(target, ''), 0);
              return true;
            }""")
            if fired:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(PAGE_WAIT_MS)
                body = clean(await page.locator("body").inner_text())
                match = re.search(r"Showing\\s+page\\s+(\\d+)\\s+of", body, re.I)
                if match and int(match.group(1)) == next_page:
                    return True
'''
if old not in text:
    raise SystemExit('PCS V6 anchor missing')
if text.count(old)!=1:
    raise SystemExit('PCS V6 anchor not unique')
text=text.replace(old,new,1)
text=text.replace('PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER','PCS_CURRENT_OPPORTUNITIES_BROWSER_V6_ASPNET_POSTBACK')
p.write_text(text,encoding='utf-8')
print('PCS V6 postback patch applied')
