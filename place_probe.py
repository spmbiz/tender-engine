from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

TARGETS=[('MUSEE_ARMEE_MULTIMEDIA','3026854','g7h'),('MONTPELLIER_VIDEO','3029544','f2h')]
BASE=Path('fresh_store/FRANCE_PLACE'); BASE.mkdir(parents=True,exist_ok=True)
res=[]
def save(d,out):
    name=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'dce.zip')[:180]; p=out/name; d.save_as(str(p)); return {'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); ctx=b.new_context(accept_downloads=True,locale='fr-FR')
    for key,cid,org in TARGETS:
        out=BASE/key; out.mkdir(parents=True,exist_ok=True); r={'key':key,'cid':cid,'status':'UNKNOWN','files':[],'error':None,'after_url':None,'responses':[]}; page=ctx.new_page(); responses=[]
        page.on('response',lambda resp: responses.append({'url':resp.url,'status':resp.status,'ct':resp.headers.get('content-type',''),'cd':resp.headers.get('content-disposition','')}))
        try:
            detail=f'https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/{cid}?orgAcronyme={org}'
            page.goto(detail,wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(600); (out/'detail.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            try:
                page.get_by_role('link',name=re.compile('Dossier de consultation',re.I)).click(timeout=7000); page.wait_for_load_state('domcontentloaded',timeout=30000); page.wait_for_timeout(400)
            except Exception:
                page.goto(f'https://www.marches-publics.gouv.fr/index.php?id={cid}&orgAcronyme={org}&page=Entreprise.EntrepriseDemandeTelechargementDce',wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(400)
            for iid in ['ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_choixAnonyme','ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions']:
                page.evaluate("id=>{const e=document.getElementById(id); e.checked=true; e.dispatchEvent(new Event('change',{bubbles:true}));}",iid)
            got=False
            try:
                with page.expect_download(timeout=7000) as di: page.locator('#ctl0_CONTENU_PAGE_validateButton').click(force=True)
                r['files'].append(save(di.value,out)); got=True
            except Exception:
                try: page.wait_for_load_state('domcontentloaded',timeout=15000)
                except: pass
                page.wait_for_timeout(900)
            r['after_url']=page.url
            try: (out/'after_submit.html').write_text(page.content(),encoding='utf-8'); (out/'after_submit.txt').write_text(page.locator('body').inner_text(timeout=10000),encoding='utf-8')
            except: pass
            # Exact full-DCE Prado anchor on the listing page.
            if not got:
                full=page.locator('#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload')
                try:
                    if full.count() and full.is_visible():
                        with page.expect_download(timeout=30000) as di: full.click(force=True)
                        r['files'].append(save(di.value,out)); got=True
                except Exception as e: r['error']='full_dce:'+repr(e)
            # Fallback: click individual document anchors containing download semantics.
            if not got:
                for sel in ["a[id*='Download']","a[id*='download']","a[id*='Telecharg']","a[id*='telecharg']","a[href*='Telecharg']","a[href*='telecharg']"]:
                    for i in range(min(page.locator(sel).count(),80)):
                        el=page.locator(sel).nth(i)
                        try:
                            with page.expect_download(timeout=10000) as di: el.click(force=True)
                            r['files'].append(save(di.value,out)); got=True; break
                        except: pass
                    if got: break
            r['responses']=[x for x in responses if re.search(r'(telecharg|download|dce|zip|consultation)',x['url'],re.I)][-100:]; (out/'responses.json').write_text(json.dumps(r['responses'],indent=2,ensure_ascii=False),encoding='utf-8'); r['status']='DOWNLOADED_PUBLIC' if got else 'NO_DOWNLOAD'
        except Exception as e: r['status']='ERROR'; r['error']=repr(e)
        finally:
            try: page.close()
            except: pass
        (out/'manifest.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8'); res.append(r)
    b.close()
print(json.dumps(res,indent=2,ensure_ascii=False))
