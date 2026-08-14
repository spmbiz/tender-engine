from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright
TARGETS=[('SCREEN_IRELAND_DATABASE','8645210'),('TEAGASC_EDITORIAL','8623183')]
BASE=Path('adapter_store/IRELAND_ETENDERS'); BASE.mkdir(parents=True,exist_ok=True)
def save(d,out):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]; p=out/n; d.save_as(str(p)); return {'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
results=[]
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    for key,res in TARGETS:
        out=BASE/key; out.mkdir(parents=True,exist_ok=True); r={'key':key,'resourceId':res,'status':'UNKNOWN','files':[],'error':None}
        ctx=b.new_context(accept_downloads=True); page=ctx.new_page()
        try:
            page.goto(f'https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId={res}',wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(700)
            (out/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            try:
                with page.expect_popup(timeout=15000) as pi: page.get_by_role('button',name=re.compile('Download Zip file',re.I)).click()
                pop=pi.value; pop.wait_for_load_state('domcontentloaded',timeout=30000); pop.wait_for_timeout(400)
                try:
                    with page.expect_download(timeout=30000) as di: pop.get_by_role('button',name=re.compile('Proceed without association',re.I)).click(force=True)
                    r['files'].append(save(di.value,out))
                except Exception as e: r['error']='popup:'+repr(e)
                pop.close()
            except Exception as e: r['error']='open_popup:'+repr(e)
            if not r['files']:
                endpoint=f'https://www.etenders.gov.ie/epps/cft/downloadCftResourceItems.do?resourceId={res}&resourceType=ContractDocument&isContract=null'
                try:
                    with page.expect_download(timeout=30000) as di: page.evaluate('(u)=>window.location.href=u',endpoint)
                    r['files'].append(save(di.value,out))
                except Exception as e: r['error']=(r['error'] or '')+' endpoint:'+repr(e)
            r['status']='DOWNLOADED_PUBLIC' if r['files'] else 'ANONYMOUS_ROUTE_NO_FILE'
        except Exception as e: r['status']='ERROR'; r['error']=repr(e)
        (out/'manifest.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8'); results.append(r); ctx.close()
    b.close()
print(json.dumps(results,indent=2,ensure_ascii=False))