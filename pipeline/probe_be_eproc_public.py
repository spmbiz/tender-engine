from __future__ import annotations

import json, os, re, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/BE_EPROC_PUBLIC'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://www.publicprocurement.be/'
NOW=datetime.now(timezone.utc);SEARCH_API='https://www.publicprocurement.be/api/sea/search/publications'

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        stats={'source':'BE_EPROC_PUBLIC','generated_at':NOW.isoformat(),'errors':[{'type':'NO_SYSTEM_CHROME'}]};(OUT/'stats.json').write_text(json.dumps(stats,indent=2));raise SystemExit(2)
    from playwright.sync_api import sync_playwright
    pw=browser=context=page=None;net=[];console=[];anchors=[];buttons=[];body='';search_requests=[];search_samples=[]
    try:
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context(locale='en-GB');page=context.new_page()
        def req(r):
            try:
                if r.url.startswith(SEARCH_API):
                    raw=r.post_data or '';parsed=None
                    try:parsed=json.loads(raw) if raw else None
                    except Exception:parsed=raw[:10000]
                    search_requests.append({'url':r.url,'method':r.method,'post_data':parsed})
            except Exception:pass
        def resp(r):
            try:
                ct=(r.headers.get('content-type') or '').lower();u=r.url
                interesting=('json' in ct or '/api/' in u.lower() or 'publication' in u.lower() or 'notice' in u.lower() or 'search' in u.lower())
                if interesting:net.append({'url':u,'status':r.status,'method':r.request.method,'content_type':ct})
            except Exception:pass
        page.on('request',req);page.on('response',resp);page.on('console',lambda m: console.append({'type':m.type,'text':m.text[:500]}))
        page.goto(BASE,wait_until='domcontentloaded',timeout=60000)
        try:page.wait_for_load_state('networkidle',timeout=18000)
        except Exception:page.wait_for_timeout(5000)
        body=page.locator('body').inner_text(timeout=10000);anchors=page.eval_on_selector_all('a[href]','els => els.map(a => ({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or [];buttons=page.eval_on_selector_all('button','els => els.map(b => ({text:(b.innerText||b.textContent||"").trim(),aria:b.getAttribute("aria-label")}))') or []
        candidate=[]
        for a in anchors:
            text=str(a.get('text') or '').lower();href=str(a.get('href') or '')
            if href.startswith('http') and any(k in (text+' '+href.lower()) for k in ('publication','publicatie','notice','bekendmaking','avis','search','recherche','zoeken','bulletin','/bda')):candidate.append(href)
        for href in list(dict.fromkeys(candidate))[:8]:
            try:
                page.goto(href,wait_until='domcontentloaded',timeout=45000)
                try:page.wait_for_load_state('networkidle',timeout=9000)
                except Exception:page.wait_for_timeout(2200)
                txt=page.locator('body').inner_text(timeout=6000);hs=page.eval_on_selector_all('a[href]','els => els.slice(0,120).map(a => ({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or []
                (OUT/f'page_{len(list(OUT.glob("page_*.json"))):02d}.json').write_text(json.dumps({'url':page.url,'body_preview':txt[:12000],'anchors':hs},ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:console.append({'type':'explore_error','text':repr(exc),'href':href})
        # Replay the exact public UI request inside its existing anonymous browser context to capture response shape.
        if search_requests and isinstance(search_requests[-1].get('post_data'),dict):
            payload=search_requests[-1]['post_data']
            try:
                sample=page.evaluate("""async ({url,payload}) => {const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(payload),credentials:'include'}); let text=await r.text(); let data=null; try{data=JSON.parse(text)}catch(e){} return {status:r.status,contentType:r.headers.get('content-type'),data:data,text:data?null:text.slice(0,20000)};}""",{'url':SEARCH_API,'payload':payload})
                search_samples.append(sample)
            except Exception as exc:search_samples.append({'error':repr(exc)})
    finally:
        try:
            if page:page.close()
        except Exception:pass
        try:
            if browser:browser.close()
        except Exception:pass
        try:
            if pw:pw.stop()
        except Exception:pass
    seen=set();network=[]
    for x in net:
        key=(x.get('method'),x.get('url'),x.get('status'))
        if key not in seen:seen.add(key);network.append(x)
    probe={'source':'BE_EPROC_PUBLIC','generated_at':NOW.isoformat(),'base':BASE,'body_preview':body[:15000],'anchors':anchors[:300],'buttons':buttons[:150],'network':network[:600],'publication_search_requests':search_requests[:20],'publication_search_samples':search_samples[:5],'console':console[:100]}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'source':'BE_EPROC_PUBLIC','generated_at':NOW.isoformat(),'raw_materialized':0,'current_materialized':0,'probe_only':True,'anchor_count':len(anchors),'network_count':len(network),'api_like_count':sum('/api/' in str(x.get('url','')).lower() for x in network),'publication_search_requests':len(search_requests),'publication_search_sample_statuses':[x.get('status') for x in search_samples if isinstance(x,dict)],'errors':[],'official_url':BASE,'public_search_api':SEARCH_API}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8');print(json.dumps(stats,indent=2));print('SEARCH_REQUESTS',json.dumps(search_requests[:5],ensure_ascii=False,indent=2));print('SEARCH_SAMPLES',json.dumps(search_samples[:2],ensure_ascii=False,indent=2)[:40000]);print('NETWORK',json.dumps(network[:100],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
