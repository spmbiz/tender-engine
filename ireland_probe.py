from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright
OUT=Path('adapter_store/IRELAND_ETENDERS'); OUT.mkdir(parents=True,exist_ok=True)
R={'key':'IRELAND_ETENDERS','status':'UNKNOWN','files':[],'popup_text':'','error':None}
def save(d):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]; p=OUT/n; d.save_as(str(p)); R['files'].append({'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); page=b.new_page(accept_downloads=True)
    try:
        page.goto('https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId=8763289',wait_until='domcontentloaded',timeout=45000)
        page.wait_for_timeout(1000)
        with page.expect_popup(timeout=15000) as pi:
            page.get_by_role('button',name=re.compile('Download Zip file',re.I)).click()
        pop=pi.value; pop.wait_for_load_state('domcontentloaded',timeout=30000); pop.wait_for_timeout(700)
        txt=pop.locator('body').inner_text(timeout=10000); R['popup_text']=txt[:5000]
        (OUT/'popup.html').write_text(pop.content(),encoding='utf-8'); (OUT/'popup.txt').write_text(txt,encoding='utf-8')
        proceed=pop.get_by_text(re.compile('PROCEED WITHOUT ASSOCIATION',re.I),exact=False)
        if proceed.count():
            try:
                with pop.expect_download(timeout=30000) as di:
                    proceed.first.click(force=True)
                save(di.value)
            except Exception as e:
                R['error']='proceed:'+repr(e)
        if not R['files']:
            controls=pop.locator('button, input[type=submit], a')
            for i in range(min(controls.count(),100)):
                el=controls.nth(i)
                try: label=((el.inner_text() or '')+' '+(el.get_attribute('value') or '')).lower()
                except Exception: continue
                if 'proceed without association' not in label: continue
                try:
                    with pop.expect_download(timeout=30000) as di: el.click(force=True)
                    save(di.value); break
                except Exception as e: R['error']=(R['error'] or '')+' fallback:'+repr(e)
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'ANONYMOUS_ROUTE_FORM_REACHED'
        pop.close()
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(R,indent=2,ensure_ascii=False))
