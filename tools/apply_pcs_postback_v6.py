from pathlib import Path

p = Path('pipeline/discover_uk_pcs_current.py')
text = p.read_text(encoding='utf-8')

old_import = 'from pathlib import Path\nfrom urllib.parse import urljoin\n'
new_import = 'from pathlib import Path\nfrom urllib.parse import urljoin\nfrom zoneinfo import ZoneInfo\n'
old_now = 'NOW = datetime.now(timezone.utc)\nMAX_PAGES = max(1, int(os.getenv("PCS_CURRENT_MAX_PAGES", "2000")))\n'
new_now = 'NOW = datetime.now(timezone.utc)\nPCS_TZ = ZoneInfo("Europe/London")\nMAX_PAGES = max(1, int(os.getenv("PCS_CURRENT_MAX_PAGES", "2000")))\n'
old_deadline = '''def parse_deadline(value):
    text = clean(value)
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None
'''
new_deadline = '''def parse_deadline(value):
    text = clean(value)
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            # PCS exposes a date but no closing clock time in the result grid.
            # Midnight would falsely expire same-day opportunities. Preserve
            # recall by treating date-only deadlines as end-of-day UK time.
            local = datetime.strptime(text, fmt).replace(
                hour=23, minute=59, second=59, tzinfo=PCS_TZ
            )
            return local.astimezone(timezone.utc)
        except Exception:
            pass
    return None
'''
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

for old, new, label in (
    (old_import, new_import, 'zoneinfo import'),
    (old_now, new_now, 'PCS timezone'),
    (old_deadline, new_deadline, 'date-only deadline'),
    (old_search, new_search, 'search race'),
):
    if old not in text:
        raise SystemExit(f'PCS V11 anchor missing: {label}')
    if text.count(old) != 1:
        raise SystemExit(f'PCS V11 anchor not unique: {label}')
    text = text.replace(old, new, 1)

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
print('PCS V11 search-race + date-only recall patch applied; proven native pager preserved')
