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
        page.wait_for_timeout(700)
        try:
            with page.expect_download(timeout=30000) as di:
                page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$notice_add_docs1$lnkZip','')")
            save(di.value)
        except Exception as e: R['error']='zip_postback:'+repr(e)
        if not R['files']:
            try:
                with page.expect_download(timeout=20000) as di:
                    page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$notice_add_docs1$grdDocuments$ctl02$Linkbutton1','')")
                save(di.value)
            except Exception as e: R['error']=(R['error'] or '')+' doc_postback:'+repr(e)
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'PUBLIC_POSTBACK_NO_DOWNLOAD'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2),encoding='utf-8'); print(json.dumps(R,indent=2))
