from pathlib import Path

p = Path('pipeline/discover_uk_pcs_current.py')
text = p.read_text(encoding='utf-8')
old = '''async def find_page_select(page):
    selects = page.locator("select")
    best = None
    best_max = 0
    best_labels = {}
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        options = sel.locator("option")
        labels = {}
        for oi in range(min(await options.count(), 2500)):
            text = clean(await options.nth(oi).inner_text())
            match = re.fullmatch(r"(?:Page\\s*)?(\\d+)", text, re.I)
            if match:
                labels[int(match.group(1))] = text
        if len(labels) >= 2 and max(labels) > best_max:
            best = sel
            best_max = max(labels)
            best_labels = labels
    return best, best_max, best_labels
'''
new = '''async def find_page_select(page):
    selects = page.locator("select")
    best = None
    best_max = 0
    best_labels = {}
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        # Read every option in one browser-context call. PCS currently exposes
        # ~1,400 Page N options; querying them one-by-one through Playwright can
        # spend tens of seconds and time out before pagination even starts.
        try:
            option_texts = await sel.evaluate(
                "el => Array.from(el.options || [], o => (o.textContent || '').trim())"
            )
        except Exception:
            continue
        labels = {}
        for option_text in option_texts or []:
            label = clean(option_text)
            match = re.fullmatch(r"(?:Page\\s*)?(\\d+)", label, re.I)
            if match:
                labels[int(match.group(1))] = label
        if len(labels) >= 2 and max(labels) > best_max:
            best = sel
            best_max = max(labels)
            best_labels = labels
    return best, best_max, best_labels
'''
if old not in text:
    raise SystemExit('PCS find_page_select anchor missing')
if text.count(old) != 1:
    raise SystemExit('PCS find_page_select anchor not unique')
text = text.replace(old, new, 1)
text = text.replace('PCS_CURRENT_OPPORTUNITIES_BROWSER_V4_POSTBACK', 'PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER')
p.write_text(text, encoding='utf-8')
print('PCS fast pager patch applied')
