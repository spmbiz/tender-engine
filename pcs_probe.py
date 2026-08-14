from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright
TARGETS=[('CULTURE_COLLECTIVE','JUL560711'),('VIDEO_PRODUCTION','JUL560975')]
BASE=Path('adapter_store/SCOTLAND_PCS'); BASE.mkdir(parents=True,exist_ok=True)
results=[]
def save(d,out):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]
    p=out/n; d.save_as(str(p))
    return {'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    for key,ref in TARGETS:
        out=BASE/key; out.mkdir(parents=True,exist_ok=True)
        r={'key':key,'ref':ref,'status':'UNKNOWN','files':[],'error':None}
        page=b.new_page(accept_downloads=True)
        try:
            page.goto(f'https://www.publiccontractsscotland.gov.uk/Search/show/Search_View.aspx?ID={ref}',wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(700)
            (out/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            try:
                with page.expect_download(timeout=30000) as di:
                    page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$notice_add_docs1$lnkZip','')")
                r['files'].append(save(di.value,out))
            except Exception as e: r['error']='zip_postback:'+repr(e)
            if not r['files']:
                for row in range(2,10):
                    try:
                        with page.expect_download(timeout=8000) as di:
                            page.evaluate(f"__doPostBack('ctl00$ContentPlaceHolder1$notice_add_docs1$grdDocuments$ctl{row:02d}$Linkbutton1','')")
                        r['files'].append(save(di.value,out)); break
                    except Exception: pass
            r['status']='DOWNLOADED_PUBLIC' if r['files'] else 'PUBLIC_POSTBACK_NO_DOWNLOAD'
        except Exception as e: r['status']='ERROR'; r['error']=repr(e)
        page.close(); (out/'manifest.json').write_text(json.dumps(r,indent=2),encoding='utf-8'); results.append(r)
    b.close()
print(json.dumps(results,indent=2))