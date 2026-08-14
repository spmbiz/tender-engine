from pathlib import Path
import hashlib, json, re
from playwright.sync_api import sync_playwright

OUT=Path('adapter_store/UNGM'); OUT.mkdir(parents=True,exist_ok=True)
result={'key':'UNGM','status':'UNKNOWN','files':[],'error':None}

def save_download(download):
    name=re.sub(r'[^A-Za-z0-9._() -]+','_',download.suggested_filename or 'download.bin')[:180]
    p=OUT/name
    download.save_as(str(p))
    result['files'].append({'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(accept_downloads=True)
    try:
        page.goto('https://www.ungm.org/Public/Notice/302249',wait_until='domcontentloaded',timeout=45000)
        page.wait_for_timeout(1000)
        links=page.locator('a[href*="DownloadDocument"]')
        for i in range(links.count()):
            try:
                with page.expect_download(timeout=15000) as info:
                    links.nth(i).click()
                save_download(info.value)
            except Exception:
                pass
        result['status']='DOWNLOADED_PUBLIC' if result['files'] else 'PUBLIC_LINKS_NO_DOWNLOAD_EVENT'
    except Exception as e:
        result['status']='ERROR'; result['error']=repr(e)
    browser.close()
(OUT/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
