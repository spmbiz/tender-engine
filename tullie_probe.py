from pathlib import Path
from playwright.sync_api import sync_playwright
import json,re,hashlib,urllib.parse

OUT=Path('fresh_store/UK_TULLIE'); OUT.mkdir(parents=True,exist_ok=True)
URL='https://tullie.org.uk/project-tullie-phase-3-gallery-brand-identity/'
R={'status':'UNKNOWN','files':[],'links':[],'error':None,'fetch_errors':[]}
def save_bytes(url,body,ct=''):
    name=urllib.parse.unquote(url.split('/')[-1].split('?')[0]) or 'document.bin'
    if '.' not in name: name += '.pdf' if 'pdf' in ct else '.bin'
    name=re.sub(r'[^A-Za-z0-9._() -]+','_',name)[:180]; fp=OUT/name; fp.write_bytes(body)
    item={'name':name,'size':len(body),'sha256':hashlib.sha256(body).hexdigest(),'url':url}
    if not any(x.get('sha256')==item['sha256'] for x in R['files']): R['files'].append(item)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); ctx=b.new_context(accept_downloads=True,user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36'); page=ctx.new_page()
    try:
        page.goto(URL,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(1200); R['title']=page.title(); R['url']=page.url
        txt=page.locator('body').inner_text(timeout=15000); (OUT/'page.txt').write_text(txt,encoding='utf-8'); (OUT/'page.html').write_text(page.content(),encoding='utf-8')
        links=[]
        for i in range(page.locator('a').count()):
            a=page.locator('a').nth(i)
            try:
                href=a.get_attribute('href'); text=' '.join((a.inner_text() or '').split())
                if href: links.append({'text':text[:250],'href':href})
            except: pass
        R['links']=links; (OUT/'links.json').write_text(json.dumps(links,indent=2,ensure_ascii=False),encoding='utf-8')
        likely=[x for x in links if re.search(r'(brief|rfq|tender|brand|identity|appendix|fees|resources|\.pdf|\.doc|\.xlsx|\.zip)',(x['text']+' '+x['href']),re.I)]
        (OUT/'likely.json').write_text(json.dumps(likely,indent=2,ensure_ascii=False),encoding='utf-8')
        for x in likely[:20]:
            href=urllib.parse.urljoin(page.url,x['href']); dp=ctx.new_page()
            try:
                resp=dp.goto(href,wait_until='commit',timeout=30000)
                if resp:
                    body=resp.body(); ct=(resp.headers.get('content-type') or '').lower()
                    if resp.ok and body and (re.search(r'\.(pdf|docx?|xlsx?|zip)(?:\?|$)',href,re.I) or any(t in ct for t in ['pdf','zip','officedocument','msword','excel'])): save_bytes(href,body,ct)
                    else: R['fetch_errors'].append({'url':href,'status':resp.status,'ct':ct,'size':len(body) if body else 0})
            except Exception as e: R['fetch_errors'].append({'url':href,'error':repr(e)})
            finally:
                try: dp.close()
                except: pass
        R['status']='DOWNLOADED_PUBLIC' if R['files'] else 'PAGE_ONLY'
    except Exception as e: R['status']='ERROR'; R['error']=repr(e)
    b.close()
(OUT/'manifest.json').write_text(json.dumps(R,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(R,indent=2,ensure_ascii=False))
