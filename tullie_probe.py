from pathlib import Path
from playwright.sync_api import sync_playwright
import json,re,hashlib,urllib.parse

OUT=Path('fresh_store/UK_TULLIE'); OUT.mkdir(parents=True,exist_ok=True)
URL='https://tullie.org.uk/project-tullie-phase-3-gallery-brand-identity/'
R={'status':'UNKNOWN','files':[],'links':[],'error':None}

def save_response(resp):
    try:
        ct=(resp.headers.get('content-type') or '').lower(); cd=(resp.headers.get('content-disposition') or '').lower()
        if not any(x in ct for x in ['application/pdf','application/zip','application/msword','officedocument']) and not re.search(r'\.(pdf|docx?|zip)(?:\?|$)',resp.url,re.I): return
        body=resp.body()
        name=urllib.parse.unquote(resp.url.split('/')[-1].split('?')[0]) or 'document.bin'
        if '.' not in name:
            ext='.pdf' if 'pdf' in ct else '.zip' if 'zip' in ct else '.bin'; name+=ext
        name=re.sub(r'[^A-Za-z0-9._() -]+','_',name)[:180]
        p=OUT/name; p.write_bytes(body)
        R['files'].append({'name':name,'size':len(body),'sha256':hashlib.sha256(body).hexdigest(),'url':resp.url})
    except Exception: pass

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page(accept_downloads=True,user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36')
    page.on('response',save_response)
    try:
        page.goto(URL,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(2000)
        R['title']=page.title(); R['url']=page.url
        txt=page.locator('body').inner_text(timeout=15000); (OUT/'page.txt').write_text(txt,encoding='utf-8')
        (OUT/'page.html').write_text(page.content(),encoding='utf-8')
        links=[]
        for i in range(page.locator('a').count()):
            a=page.locator('a').nth(i)
            try:
                href=a.get_attribute('href'); text=' '.join((a.inner_text() or '').split())
                if href: links.append({'text':text[:250],'href':href})
            except: pass
        R['links']=links
        (OUT/'links.json').write_text(json.dumps(links,indent=2,ensure_ascii=False),encoding='utf-8')
        # Navigate/download all likely tender-doc links.
        likely=[x for x in links if re.search(r'(brief|rfq|tender|brand|identity|download|\.pdf|\.doc|\.zip)',(x['text']+' '+x['href']),re.I)]
        (OUT/'likely.json').write_text(json.dumps(likely,indent=2,ensure_ascii=False),encoding='utf-8')
        for idx,x in enumerate(likely[:20]):
            href=urllib.parse.urljoin(page.url,x['href'])
            try:
                with page.expect_download(timeout=5000) as di:
                    page.evaluate('(u)=>window.open(u,"_blank")',href)
                d=di.value; name=re.sub(r'[^A-Za-z0-9._() -]+','_',d.suggested_filename or f'doc{idx}.bin')[:180]; fp=OUT/name; d.save_as(str(fp)); R['files'].append({'name':name,'size':fp.stat().st_size,'sha256':hashlib.sha256(fp.read_bytes()).hexdigest(),'url':href})
            except Exception: pass
        R['status']='OK'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(R,indent=2,ensure_ascii=False))
