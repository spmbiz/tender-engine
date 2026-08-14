from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright

TARGETS=[
 ('MUSEE_ARMEE_MULTIMEDIA','3026854','g7h'),
 ('MONTPELLIER_VIDEO','3029544','f2h'),
]
BASE=Path('fresh_store/FRANCE_PLACE'); BASE.mkdir(parents=True,exist_ok=True)
res=[]

def save(d,out):
    name=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'dce.zip')[:180]
    p=out/name; d.save_as(str(p))
    return {'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    ctx=b.new_context(accept_downloads=True,locale='fr-FR')
    for key,cid,org in TARGETS:
        out=BASE/key; out.mkdir(parents=True,exist_ok=True)
        r={'key':key,'cid':cid,'status':'UNKNOWN','files':[],'error':None}
        page=ctx.new_page()
        try:
            detail=f'https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/{cid}?orgAcronyme={org}'
            page.goto(detail,wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(800)
            (out/'detail.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            (out/'detail.html').write_text(page.content(),encoding='utf-8')
            # Click Dossier de consultation if possible; fallback direct legacy request page.
            try:
                page.get_by_role('link',name=re.compile('Dossier de consultation',re.I)).click(timeout=7000)
                page.wait_for_load_state('domcontentloaded',timeout=30000); page.wait_for_timeout(500)
            except Exception:
                u=f'https://www.marches-publics.gouv.fr/index.php?id={cid}&orgAcronyme={org}&page=Entreprise.EntrepriseDemandeTelechargementDce'
                page.goto(u,wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(500)
            (out/'download_page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            (out/'download_page.html').write_text(page.content(),encoding='utf-8')
            # anonymous radio/checkbox
            anon=page.get_by_text(re.compile('télécharger anonymement',re.I))
            try: anon.click(timeout=5000)
            except Exception:
                for el in page.locator('input[type=radio]').all():
                    try:
                        val=(el.get_attribute('value') or '')+' '+(el.get_attribute('id') or '')+' '+(el.get_attribute('name') or '')
                        if 'anon' in val.lower(): el.check(force=True); break
                    except Exception: pass
            # accept CGU checkbox(es)
            for i in range(page.locator('input[type=checkbox]').count()):
                el=page.locator('input[type=checkbox]').nth(i)
                try:
                    if el.is_visible(): el.check(force=True)
                except Exception: pass
            page.wait_for_timeout(300)
            # Save controls for debugging
            controls=[]
            for sel in ['button','input[type=submit]','a']:
                for i in range(min(page.locator(sel).count(),80)):
                    el=page.locator(sel).nth(i)
                    try: controls.append({'tag':sel,'text':el.inner_text()[:200] if sel!='input[type=submit]' else '', 'value':el.get_attribute('value'),'id':el.get_attribute('id'),'name':el.get_attribute('name'),'href':el.get_attribute('href')})
                    except Exception: pass
            (out/'controls.json').write_text(json.dumps(controls,indent=2,ensure_ascii=False),encoding='utf-8')
            candidates=[]
            for pattern in ['Télécharger','Valider','Continuer','Download']:
                try:
                    loc=page.get_by_role('button',name=re.compile(pattern,re.I))
                    for i in range(loc.count()): candidates.append(loc.nth(i))
                except Exception: pass
            for i in range(page.locator('input[type=submit]').count()): candidates.append(page.locator('input[type=submit]').nth(i))
            got=False
            for el in candidates:
                try:
                    if not el.is_visible(): continue
                    with page.expect_download(timeout=20000) as di:
                        el.click(force=True)
                    r['files'].append(save(di.value,out)); got=True; break
                except Exception as e:
                    r['error']='click:'+repr(e)
            r['status']='DOWNLOADED_PUBLIC' if got else 'NO_DOWNLOAD'
        except Exception as e:
            r['status']='ERROR'; r['error']=repr(e)
        finally:
            try: page.close()
            except: pass
        (out/'manifest.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
        res.append(r)
    b.close()
print(json.dumps(res,indent=2,ensure_ascii=False))
