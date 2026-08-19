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
                # before clicking; otherwise the caller can read the stale All
                # Notices grid while the Current Opportunity POST is starting.
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

if old_search not in text:
    raise SystemExit('PCS search-race anchor missing')
if text.count(old_search) != 1:
    raise SystemExit('PCS search-race anchor not unique')
text = text.replace(old_search, new_search, 1)

for old_contract in (
    'PCS_CURRENT_OPPORTUNITIES_BROWSER_V8_NATIVE_ONCHANGE',
    'PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER',
):
    if old_contract in text:
        text = text.replace(old_contract, 'PCS_CURRENT_OPPORTUNITIES_BROWSER_V11_NAV_SAFE_SEARCH_NATIVE_PAGER', 1)
        break
else:
    raise SystemExit('PCS expected listing contract missing')

p.write_text(text, encoding='utf-8')
print('PCS V11 search-race patch applied; proven native pager preserved')
