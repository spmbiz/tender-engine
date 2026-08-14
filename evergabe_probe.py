from pathlib import Path
import json,re,hashlib
from playwright.sync_api import sync_playwright
OUT=Path('adapter_store/DE_EVERGABE'); OUT.mkdir(parents=True,exist_ok=True)
R={'key':'DE_EVERGABE','status':'UNKNOWN','files':[],'error':None}
def save(d):
    n=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or 'download.bin')[:180]; p=OUT/n; d.save_as(str(p)); R['files'].append({'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); page=b.new_page(accept_downloads=True)
    try:
        page.goto('https://www.evergabe-online.de/tenderdocuments.html?id=857557',wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(1000)
        links=page.get_by_text(re.compile('Als ZIP-Datei herunterladen',re.I))
        if links.count():
            try:
                with page.expect_download(timeout=30000) as di: links.first.click()
                save(di.value)
            except Exception as e: R['error']=repr(e)
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'PUBLIC_DOC_LIST_NO_DOWNLOAD'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2),encoding='utf-8'); print(json.dumps(R,indent=2))
