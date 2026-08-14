from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--url',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--label',required=True)
    args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)

    from playwright.sync_api import sync_playwright
    result={'label':args.label,'start_url':args.url,'final_url':None,'title':None,'captcha':False,'auth':False,'downloads':[],'links':[],'forms':[],'inputs':[],'buttons':[],'status':'STARTED','error':None}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        ctx=browser.new_context(accept_downloads=True)
        page=ctx.new_page()
        try:
            page.goto(args.url,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(1200)
            result['final_url']=page.url
            result['title']=page.title()
            body=page.locator('body').inner_text(timeout=15000)
            html=page.content()
            (out/'body.txt').write_text(body,encoding='utf-8')
            (out/'page.html').write_text(html,encoding='utf-8')
            low=body.lower()
            result['captcha']=bool(re.search(r'captcha|texte de l.image|code de sécurité|security code|recaptcha',low,re.I))
            result['auth']=bool(re.search(r'connexion|identifi|login|mot de passe|sign in|compte',low,re.I))
            result['links']=page.locator('a').evaluate_all("els=>els.slice(0,500).map(e=>({text:(e.innerText||'').trim(),href:e.href||e.getAttribute('href')}))")
            result['forms']=page.locator('form').evaluate_all("els=>els.slice(0,50).map(e=>({action:e.action,method:e.method,id:e.id,name:e.name}))")
            result['inputs']=page.locator('input').evaluate_all("els=>els.slice(0,200).map(e=>({type:e.type,name:e.name,id:e.id,value:(e.type==='hidden'?e.value:null)}))")
            result['buttons']=page.locator('button,input[type=submit],input[type=button]').evaluate_all("els=>els.slice(0,100).map(e=>({text:(e.innerText||e.value||'').trim(),id:e.id,name:e.name,type:e.type}))")

            # Never submit or interact when a CAPTCHA is present. We only record the public surface.
            if result['captcha']:
                result['status']='CAPTCHA_REQUIRED'
            else:
                # Try obvious public direct document links first. No credentials/forms are submitted.
                candidates=[]
                for item in result['links']:
                    text=(item.get('text') or '')
                    href=item.get('href') or ''
                    if href and re.search(r'dce|dossier|document|download|télécharg|telecharg|pi[eè]ce',text+' '+href,re.I):
                        candidates.append((text,href))
                seen=set()
                for text,href in candidates[:15]:
                    if not href or href in seen: continue
                    seen.add(href)
                    try:
                        r=ctx.request.get(href,timeout=30000)
                        ct=(r.headers.get('content-type') or '').lower()
                        cd=(r.headers.get('content-disposition') or '').lower()
                        bodyb=r.body()
                        if r.ok and bodyb and ('attachment' in cd or any(x in ct for x in ['application/pdf','application/zip','application/octet-stream','application/vnd'])):
                            ext='.bin'
                            if 'pdf' in ct: ext='.pdf'
                            elif 'zip' in ct: ext='.zip'
                            fn=out/f'download_{len(result["downloads"])+1}{ext}'
                            fn.write_bytes(bodyb)
                            result['downloads'].append({'source_url':href,'link_text':text,'file':fn.name,'size':fn.stat().st_size,'sha256':sha256(fn),'content_type':ct})
                    except Exception:
                        pass
                result['status']='DOWNLOADED_PUBLIC' if result['downloads'] else ('AUTH_REQUIRED' if result['auth'] else 'PUBLIC_PAGE_NO_DIRECT_FILE')
        except Exception as exc:
            result['status']='ERROR_RETRYABLE'; result['error']=repr(exc)
        finally:
            browser.close()
    (out/'probe.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'links','forms','inputs','buttons'}},indent=2,ensure_ascii=False))

if __name__=='__main__': main()
