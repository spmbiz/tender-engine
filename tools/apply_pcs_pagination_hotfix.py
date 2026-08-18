from pathlib import Path

p = Path('pipeline/discover_uk_pcs_current.py')
text = p.read_text(encoding='utf-8')
old_advance = '''            await selector.select_option(label=labels.get(next_page, f"Page {next_page}"))
            await page.wait_for_timeout(PAGE_WAIT_MS)
            after = clean(await page.locator("body").inner_text())[:5000]
            if after != before_signature:
                return True
'''
new_advance = '''            await selector.select_option(label=labels.get(next_page, f"Page {next_page}"))
            await page.wait_for_timeout(PAGE_WAIT_MS)
            # A successful select/postback is enough to continue. The main loop
            # verifies the actual result-row signature on the next iteration,
            # so an ineffective postback cannot silently count as progress.
            return True
'''
old_signature = '''                signature = clean(await page.locator("body").inner_text())[:5000]
                if signature in seen_signatures:
                    warnings.append({"type": "REPEATED_PAGE_SIGNATURE", "page": pages + 1})
                    break
'''
new_signature = '''                body_text = clean(await page.locator("body").inner_text())
                refs = tuple(re.findall(r"Reference\\s*No:\\s*([^\\s]+)", body_text, re.I))
                signature = refs if refs else (body_text[-5000:],)
                if signature in seen_signatures:
                    warnings.append({"type": "REPEATED_PAGE_SIGNATURE", "page": pages + 1})
                    break
'''
for old, new, label in ((old_advance, new_advance, 'advance'), (old_signature, new_signature, 'signature')):
    if old not in text:
        raise SystemExit(f'PCS hotfix anchor missing: {label}')
    if text.count(old) != 1:
        raise SystemExit(f'PCS hotfix anchor not unique: {label}')
    text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')
print('PCS pagination hotfix applied')
