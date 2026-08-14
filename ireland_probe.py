from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright
RESOURCE='8535600'
OUT=Path('adapter_store/IRELAND_ETENDERS/ELEARNING_CHILDRENS_RIGHTS'); OUT.mkdir(parents=True,exist_ok=True)
R={'key':'IRELAND_ELEARNING','resourceId':RESOURCE,'status':'UNKNOWN','files':[],'popup_text':'','error':None}
def save(d):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]; p=OUT/n; d.save_as(str(p)); R['files'].append({'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); ctx=b.new_context(accept_downloads=True); page=ctx.new_page()
    try:
        page.goto(f'https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId={RESOURCE}',wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(700)
        (OUT/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
        with page.expect_popup(timeout=15000) as pi:
            page.get_by_role('button',name=re.compile('Download Zip file',re.I)).click()
        pop=pi.value; pop.wait_for_load_state('domcontentloaded',timeout=30000); pop.wait_for_timeout(500)
        txt=pop.locator('body').inner_text(timeout=10000); R['popup_text']=txt[:5000]
        try:
            with page.expect_download(timeout=30000) as di:
                pop.get_by_role('button',name=re.compile('Proceed without association',re.I)).click(force=True)
            save(di.value)
        except Exception as e: R['error']='opener_download:'+repr(e)
        if not R['files']:
            endpoint=f'https://www.etenders.gov.ie/epps/cft/downloadCftResourceItems.do?resourceId={RESOURCE}&resourceType=ContractDocument&isContract=null'
            try:
                with page.expect_download(timeout=30000) as di: page.evaluate('(u)=>window.location.href=u',endpoint)
                save(di.value)
            except Exception as e: R['error']=(R['error'] or '')+' endpoint:'+repr(e)
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'ANONYMOUS_ROUTE_NO_FILE'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(R,indent=2,ensure_ascii=False))