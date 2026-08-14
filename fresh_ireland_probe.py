from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright

TARGETS=[
    ('PUBLICART_EDITORIAL','8772739'),
    ('HRB_DESIGN_PRINT_WEB','8766381'),
    ('NENAGH_INTERPRETATION_AV','8806179'),
    ('AI_UPSKILLING_ENGINEERS','8753790'),
    ('DRCC_MEDIA_BUYING','8795608'),
]
BASE=Path('fresh_store/IRELAND_ETENDERS'); BASE.mkdir(parents=True,exist_ok=True)
results=[]

def save(d,out):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]
    p=out/n
    d.save_as(str(p))
    return {'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    ctx=b.new_context(accept_downloads=True)
    for key,resource in TARGETS:
        out=BASE/key; out.mkdir(parents=True,exist_ok=True)
        r={'key':key,'resourceId':resource,'status':'UNKNOWN','files':[],'page_title':'','page_text':'','error':None}
        page=ctx.new_page()
        try:
            url=f'https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId={resource}'
            page.goto(url,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(700)
            r['page_title']=page.title()
            txt=page.locator('body').inner_text(timeout=15000)
            r['page_text']=txt[:12000]
            (out/'page.txt').write_text(txt,encoding='utf-8')
            # Preferred anonymous UI route.
            try:
                with page.expect_popup(timeout=8000) as pi:
                    page.get_by_role('button',name=re.compile('Download Zip file',re.I)).click()
                pop=pi.value
                pop.wait_for_load_state('domcontentloaded',timeout=20000)
                pop.wait_for_timeout(300)
                (out/'popup.txt').write_text(pop.locator('body').inner_text(timeout=10000),encoding='utf-8')
                try:
                    with page.expect_download(timeout=25000) as di:
                        pop.get_by_role('button',name=re.compile('Proceed without association',re.I)).click(force=True)
                    r['files'].append(save(di.value,out))
                except Exception as e:
                    r['error']='opener_download:'+repr(e)
                try: pop.close()
                except Exception: pass
            except Exception as e:
                r['error']='popup:'+repr(e)
            # Deterministic public fallback exposed by the portal JS.
            if not r['files']:
                endpoint=f'https://www.etenders.gov.ie/epps/cft/downloadCftResourceItems.do?resourceId={resource}&resourceType=ContractDocument&isContract=null'
                try:
                    with page.expect_download(timeout=30000) as di:
                        page.evaluate('(u)=>window.location.href=u',endpoint)
                    r['files'].append(save(di.value,out))
                except Exception as e:
                    r['error']=(r['error'] or '')+' endpoint:'+repr(e)
            r['status']='DOWNLOADED_PUBLIC' if r['files'] else 'NO_PUBLIC_FILE'
        except Exception as e:
            r['status']='ERROR'; r['error']=repr(e)
        finally:
            try: page.close()
            except Exception: pass
        (out/'manifest.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
        results.append(r)
    b.close()

(BASE/'summary.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(results,indent=2,ensure_ascii=False))
