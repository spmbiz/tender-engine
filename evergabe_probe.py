from pathlib import Path
import json,re,hashlib
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
OUT=Path('adapter_store/DE_EVERGABE'); OUT.mkdir(parents=True,exist_ok=True)
R={'key':'DE_EVERGABE','status':'UNKNOWN','files':[],'links':[],'error':None}
def save(d):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]; p=OUT/n; d.save_as(str(p)); R['files'].append({'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); page=b.new_page(accept_downloads=True)
    try:
        page.goto('https://www.evergabe-online.de/tenderdocuments.html?id=857557',wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(900)
        (OUT/'page.html').write_text(page.content(),encoding='utf-8')
        (OUT/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
        candidates=[]
        for a in page.locator('a[href]').all():
            try:
                href=a.get_attribute('href') or ''; text=(a.inner_text() or '').strip(); absu=urljoin(page.url,href)
            except Exception: continue
            low=(text+' '+href).lower()
            if any(x in low for x in ['zip','herunterladen','download','tenderdocument','unterlage','dokument']):
                candidates.append({'text':text[:180],'href':absu})
        R['links']=candidates
        for c in candidates:
            if R['files']: break
            loc=page.locator(f'a[href="{c["href"]}"]') if c['href'].startswith('http') else None
            try:
                # Prefer navigating directly when link is a normal href.
                with page.expect_download(timeout=30000) as di:
                    page.evaluate('(u)=>window.location.href=u',c['href'])
                save(di.value)
            except Exception:
                continue
        if not R['files']:
            textloc=page.get_by_text(re.compile('ZIP.*herunterladen|herunterladen.*ZIP|Download',re.I))
            for i in range(min(textloc.count(),10)):
                try:
                    with page.expect_download(timeout=25000) as di: textloc.nth(i).click(force=True)
                    save(di.value); break
                except Exception: pass
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'PUBLIC_DOC_LIST_NO_DOWNLOAD'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(R,indent=2,ensure_ascii=False))
