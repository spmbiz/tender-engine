from pathlib import Path

p = Path('pipeline/discover_uk_pcs_current.py')
text = p.read_text(encoding='utf-8')

old_submit = '''async def submit_search(page, telemetry):
    candidates = [
        page.get_by_role("button", name=re.compile(r"^search$", re.I)),
        page.locator("input[type=submit]").filter(has=page.locator("xpath=.")),
    ]
    for loc in candidates:
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 20)):
            node = loc.nth(i)
            try:
                text = clean(await node.get_attribute("value") or await node.inner_text())
                if text and "search" not in text.lower() and loc is candidates[1]:
                    continue
                await node.click(timeout=5000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["search_submitted"] = True
                return True
            except Exception:
                continue
    telemetry["search_submitted"] = False
    return False
'''

new_submit = '''async def submit_search(page, telemetry):
    candidates = [
        page.get_by_role("button", name=re.compile(r"^search$", re.I)),
        page.locator("input[type=submit]"),
        page.locator("input[type=image][alt*='search' i], input[type=image][title*='search' i]"),
        page.locator("input[type=button][value*='search' i]"),
        page.locator("a[id*='search' i], button[id*='search' i], [onclick*='search' i]"),
        page.get_by_text(re.compile(r"^\\s*search\\s*$", re.I)),
    ]
    debug = []
    for loc in candidates:
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 30)):
            node = loc.nth(i)
            try:
                if not await node.is_visible():
                    continue
                meta = await node.evaluate("el => ({tag:el.tagName,id:el.id||'',name:el.getAttribute('name')||'',value:el.getAttribute('value')||'',type:el.getAttribute('type')||'',text:(el.innerText||'').trim()})")
                debug.append(meta)
                hay = clean(' '.join(str(meta.get(k) or '') for k in ('id','name','value','text')))
                if 'search' not in hay.lower():
                    continue
                await node.click(timeout=5000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["search_submitted"] = "CONTROL_CLICK"
                telemetry["search_control"] = meta
                return True
            except Exception:
                continue

    # PCS is classic ASP.NET and some renders expose no semantic Search button
    # to Playwright. The selected Notice Type is still a normal form control, so
    # submit its owning form directly. This uses the page's own public form and
    # preserves all ViewState/filter values; it does not bypass any access gate.
    selects = page.locator("select")
    for i in range(await selects.count()):
        sel = selects.nth(i)
        try:
            selected = clean(await sel.locator("option:checked").inner_text())
        except Exception:
            selected = ''
        if not current_option(selected):
            continue
        try:
            fired = await sel.evaluate("""el => {
              const form = el.form;
              if (!form) return false;
              setTimeout(() => {
                if (typeof form.requestSubmit === 'function') form.requestSubmit();
                else form.submit();
              }, 0);
              return true;
            }""")
            if fired:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(PAGE_WAIT_MS)
                telemetry["search_submitted"] = "FORM_FALLBACK"
                telemetry["search_controls_debug"] = debug[:40]
                return True
        except Exception:
            continue

    telemetry["search_submitted"] = False
    telemetry["search_controls_debug"] = debug[:40]
    return False
'''

old_advance = '''async def advance(page, next_page, before_signature):
    selector, _, labels = await find_page_select(page)
    if selector is not None:
        try:
            await selector.select_option(label=labels.get(next_page, f"Page {next_page}"))
            await page.wait_for_timeout(PAGE_WAIT_MS)
            # A successful select/postback is enough to continue. The main loop
            # verifies the actual result-row signature on the next iteration,
            # so an ineffective postback cannot silently count as progress.
            return True
        except Exception:
            pass
'''

new_advance = '''async def advance(page, next_page, before_signature):
    selector, _, labels = await find_page_select(page)
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

for old, new, label in ((old_submit, new_submit, 'submit_search'), (old_advance, new_advance, 'advance')):
    if old not in text:
        raise SystemExit(f'PCS V4 anchor missing: {label}')
    if text.count(old) != 1:
        raise SystemExit(f'PCS V4 anchor not unique: {label}')
    text = text.replace(old, new, 1)

text = text.replace('PCS_CURRENT_OPPORTUNITIES_BROWSER_V3', 'PCS_CURRENT_OPPORTUNITIES_BROWSER_V4_POSTBACK', 1)
p.write_text(text, encoding='utf-8')
print('PCS V4 postback patch applied')
