from __future__ import annotations

import json, os, re, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/BE_EPROC_PUBLIC'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://www.publicprocurement.be/'
NOW=datetime.now(timezone.utc);SEARCH_API='https://www.publicprocurement.be/api/sea/search/publications'

def redact_headers(headers: dict) -> dict:
    out={}
    for k,v in (headers or {}).items():
        lk=str(k).lower()
        if lk in {'authorization','cookie','set-cookie'}:
            out[k]='<present>' if v else '<empty>'
        elif lk.startswith('sec-') or lk in {'content-length'}:
            continue
        else:
            out[k]=v
    return out

def shape(data):
    if isinstance(data,dict):
        return {'type':'dict','keys':list(data.keys())[:80],**{k:len(v) for k,v in data.items() if isinstance(v,list)}}
    if isinstance(data,list):return {'type':'list','length':len(data)}
    return {'type':type(data).__name__}

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        stats={'source':'BE_EPROC_PUBLIC','generated_at':NOW.isoformat(),'errors':[{'type':'NO_SYSTEM_CHROME'}]};(OUT/'stats.json').write_text(json.dumps(stats,indent=2));raise SystemExit(2)
    from playwright.sync_api import sync_playwright
    pw=browser=context=page=None;net=[];console=[];anchors=[];buttons=[];body='';search_requests=[];search_samples=[];live_headers=[]
    try:
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context(locale='en-GB');page=context.new_page()
        def req(r):
            try:
                if r.url.startswith(SEARCH_API):
                    raw=r.post_data or '';parsed=None
                    try:parsed=json.loads(raw) if raw else None
                    except Exception:parsed=raw[:10000]
                    hdr=r.all_headers()
                    live_headers.append(hdr)
                    search_requests.append({'url':r.url,'method':r.method,'post_data':parsed,'headers':redact_headers(hdr),'authorization_present':bool(hdr.get('authorization'))})
            except Exception as exc:console.append({'type':'request_capture_error','text':repr(exc)})
        def resp(r):
            try:
                ct=(r.headers.get('content-type') or '').lower();u=r.url
                interesting=('json' in ct or '/api/' in u.lower() or 'publication' in u.lower() or 'notice' in u.lower() or 'search' in u.lower())
                if interesting:net.append({'url':u,'status':r.status,'method':r.request.method,'content_type':ct})
                if u.startswith(SEARCH_API) and r.status==200:
                    data=r.json()
                    search_samples.append({'status':r.status,'content_type':ct,'shape':shape(data),'data':data})
            except Exception as exc:
                if getattr(r,'url','').startswith(SEARCH_API):console.append({'type':'response_capture_error','text':repr(exc)})
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
        # Reuse the exact anonymous UI headers in-memory only. Never persist bearer/cookie values.
        if search_requests and live_headers and isinstance(search_requests[-1].get('post_data'),dict):
            payload=search_requests[-1]['post_data'];hdr=live_headers[-1]
            replay_headers={k:v for k,v in hdr.items() if k.lower() in {'authorization','content-type','accept','accept-language','x-xsrf-token','x-requested-with'}}
            try:
                rr=context.request.post(SEARCH_API,headers=replay_headers,data=payload,timeout=30000)
                text=rr.text();data=None
                try:data=json.loads(text)
                except Exception:pass
                search_samples.append({'status':rr.status,'content_type':rr.headers.get('content-type'),'shape':shape(data) if data is not None else {'type':'text'},'data':data,'text':None if data is not None else text[:2000],'replay':True})
            except Exception as exc:search_samples.append({'error':repr(exc),'replay':True})
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
    safe_samples=[]
    for x in search_samples[:5]:
        y=dict(x)
        # Persist at most a bounded public response sample. No request credentials are included.
        if isinstance(y.get('data'),dict):
            raw=json.dumps(y['data'],ensure_ascii=False)
            if len(raw)>250000:y['data_preview']=raw[:250000];y.pop('data',None)
        safe_samples.append(y)
    probe={'source':'BE_EPROC_PUBLIC','generated_at':NOW.isoformat(),'base':BASE,'body_preview':body[:15000],'anchors':anchors[:300],'buttons':buttons[:150],'network':network[:600],'publication_search_requests':search_requests[:20],'publication_search_samples':safe_samples,'console':console[:100]}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    live200=[x for x in search_samples if isinstance(x,dict) and x.get('status')==200]
    errors=[] if live200 else [{'type':'NO_SUCCESSFUL_PUBLICATION_SEARCH_RESPONSE'}]
    stats={'source':'BE_EPROC_PUBLIC','generated_at':NOW.isoformat(),'raw_materialized':0,'current_materialized':0,'probe_only':True,'anchor_count':len(anchors),'network_count':len(network),'api_like_count':sum('/api/' in str(x.get('url','')).lower() for x in network),'publication_search_requests':len(search_requests),'publication_search_sample_statuses':[x.get('status') for x in search_samples if isinstance(x,dict)],'successful_search_samples':len(live200),'errors':errors,'official_url':BASE,'public_search_api':SEARCH_API}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8');print(json.dumps(stats,indent=2));print('SEARCH_REQUESTS',json.dumps(search_requests[:5],ensure_ascii=False,indent=2));print('SEARCH_SAMPLES',json.dumps(safe_samples[:3],ensure_ascii=False,indent=2)[:120000]);print('NETWORK',json.dumps(network[:100],ensure_ascii=False,indent=2))
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
