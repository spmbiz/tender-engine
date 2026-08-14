from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright
OUT=Path('adapter_store/SCOTLAND_PCS'); OUT.mkdir(parents=True,exist_ok=True)
R={'key':'SCOTLAND_PCS','status':'UNKNOWN','files':[],'error':None}
def save(d):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]; p=OUT/n; d.save_as(str(p)); R['files'].append({'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); page=b.new_page(accept_downloads=True)
    try:
        page.goto('https://www.publiccontractsscotland.gov.uk/Search/show/Search_View.aspx?ID=FEB549835',wait_until='domcontentloaded',timeout=45000)
        page.wait_for_timeout(1000)
        z=page.locator('#ctl00_ContentPlaceHolder1_notice_add_docs1_lnkZip')
        if z.count():
            try:
                with page.expect_download(timeout=30000) as di: z.click()
                save(di.value)
            except Exception as e: R['error']='zip:'+repr(e)
        if not R['files']:
            d=page.locator('#ctl00_ContentPlaceHolder1_notice_add_docs1_grdDocuments_ctl02_Linkbutton1')
            if d.count():
                try:
                    with page.expect_download(timeout=20000) as di: d.click()
                    save(di.value)
                except Exception as e: R['error']=(R['error'] or '')+' doc:'+repr(e)
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'PUBLIC_POSTBACK_NO_DOWNLOAD'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2),encoding='utf-8'); print(json.dumps(R,indent=2))
