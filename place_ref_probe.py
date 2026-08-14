from pathlib import Path
import json,re,hashlib,urllib.parse
from playwright.sync_api import sync_playwright

REF='DDTM-STA-2026-01'
OUT=Path('fresh_store/FRANCE_PLACE_REF')/REF; OUT.mkdir(parents=True,exist_ok=True)
R={'ref':REF,'status':'UNKNOWN','search_url':None,'detail_url':None,'cid':None,'files':[],'error':None,'links':[]}
def save(d):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'dce.zip')[:180]; p=OUT/n; d.save_as(str(p)); return {'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); ctx=b.new_context(accept_downloads=True,locale='fr-FR'); page=ctx.new_page()
    try:
        u='https://www.marches-publics.gouv.fr/?keyWord='+urllib.parse.quote(REF)+'&page=Entreprise.EntrepriseAdvancedSearch&searchAnnCons='
        R['search_url']=u; page.goto(u,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(1000)
        txt=page.locator('body').inner_text(timeout=15000); (OUT/'search.txt').write_text(txt,encoding='utf-8'); (OUT/'search.html').write_text(page.content(),encoding='utf-8')
        links=[]
        for i in range(page.locator('a').count()):
            a=page.locator('a').nth(i)
            try:
                h=a.get_attribute('href'); t=' '.join((a.inner_text() or '').split())
                if h: links.append({'text':t[:300],'href':urllib.parse.urljoin(page.url,h)})
            except: pass
        R['links']=links; (OUT/'links.json').write_text(json.dumps(links,indent=2,ensure_ascii=False),encoding='utf-8')
        # Prefer links near exact reference / consultation URL.
        cand=[x for x in links if '/app.php/entreprise/consultation/' in x['href']]
        if not cand:
            # inspect hrefs around any row containing ref
            rows=page.locator('tr')
            for i in range(rows.count()):
                tr=rows.nth(i)
                try:
                    if REF.lower() not in tr.inner_text().lower(): continue
                    for j in range(tr.locator('a').count()):
                        h=tr.locator('a').nth(j).get_attribute('href')
                        if h: cand.append({'text':'row','href':urllib.parse.urljoin(page.url,h)})
                except: pass
        if not cand: raise RuntimeError('No consultation link discovered')
        detail=next((x['href'] for x in cand if '/consultation/' in x['href']),cand[0]['href'])
        R['detail_url']=detail; m=re.search(r'/consultation/(\d+)',detail); R['cid']=m.group(1) if m else None
        page.goto(detail,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(700); (OUT/'detail.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
        # DCE link/form
        try:
            page.get_by_role('link',name=re.compile('Dossier de consultation',re.I)).click(timeout=8000); page.wait_for_load_state('domcontentloaded',timeout=30000); page.wait_for_timeout(500)
        except: pass
        # anonymous form if present
        for iid in ['ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_choixAnonyme','ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions']:
            if page.locator('#'+iid).count(): page.evaluate("id=>{const e=document.getElementById(id);e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}",iid)
        if page.locator('#ctl0_CONTENU_PAGE_validateButton').count():
            try:
                with page.expect_download(timeout=7000) as di: page.locator('#ctl0_CONTENU_PAGE_validateButton').click(force=True)
                R['files'].append(save(di.value))
            except:
                try: page.wait_for_load_state('domcontentloaded',timeout=15000)
                except: pass
                page.wait_for_timeout(1000)
        (OUT/'after.txt').write_text(page.locator('body').inner_text(timeout=10000),encoding='utf-8'); (OUT/'after.html').write_text(page.content(),encoding='utf-8')
        if not R['files']:
            full=page.locator('#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload')
            if full.count():
                try:
                    with page.expect_download(timeout=30000) as di: full.click(force=True)
                    R['files'].append(save(di.value))
                except Exception as e: R['error']='full:'+repr(e)
        if not R['files']:
            for sel in ["a[id*='Download']","a[id*='Telecharg']","a[href*='Telecharg']","a[href*='.zip']"]:
                for i in range(min(page.locator(sel).count(),60)):
                    try:
                        with page.expect_download(timeout=12000) as di: page.locator(sel).nth(i).click(force=True)
                        R['files'].append(save(di.value)); break
                    except: pass
                if R['files']: break
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'DISCOVERED_NO_DOWNLOAD'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(R,indent=2,ensure_ascii=False))
