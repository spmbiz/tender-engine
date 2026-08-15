from __future__ import annotations

import json, os, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/CZ_ZAKAZKY_GOV'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://zakazky.gov.cz/'
NOW=datetime.now(timezone.utc)

def shape(data):
    if isinstance(data,dict):
        return {'type':'dict','keys':list(data.keys())[:100],**{k:len(v) for k,v in data.items() if isinstance(v,list)}}
    if isinstance(data,list):return {'type':'list','length':len(data)}
    return {'type':type(data).__name__}

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        s={'source':'CZ_ZAKAZKY_GOV','raw_materialized':0,'current_materialized':0,'errors':[{'type':'NO_SYSTEM_CHROME'}]};(OUT/'stats.json').write_text(json.dumps(s,indent=2));raise SystemExit(2)
    from playwright.sync_api import sync_playwright
    pw=browser=context=page=None;net=[];reqs=[];samples=[];body='';anchors=[]
    try:
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context(locale='cs-CZ');page=context.new_page()
        def request(r):
            try:
                u=r.url.lower()
                if '/api/' in u or 'api.isd.nipez.cz/' in u or any(k in u for k in ('zakazk','search','tender','procurement')):
                    raw=r.post_data or '';parsed=None
                    try:parsed=json.loads(raw) if raw else None
                    except Exception:parsed=raw[:6000]
                    reqs.append({'url':r.url,'method':r.method,'post_data':parsed})
            except Exception:pass
        def response(r):
            try:
                ct=(r.headers.get('content-type') or '').lower();u=r.url.lower()
                interesting=('json' in ct or '/api/' in u or 'api.isd.nipez.cz/' in u or any(k in u for k in ('search','zakazk','tender')))
                if interesting:net.append({'url':r.url,'status':r.status,'method':r.request.method,'content_type':ct})
                if r.status==200 and 'json' in ct and ('api.isd.nipez.cz/' in u or 'api.zsd.nipez.cz/' in u):
                    data=r.json();raw=json.dumps(data,ensure_ascii=False)
                    samples.append({'url':r.url,'status':r.status,'shape':shape(data),'data':data if len(raw)<=400000 else None,'data_preview':None if len(raw)<=400000 else raw[:400000]})
            except Exception as exc:
                samples.append({'url':getattr(r,'url',''),'capture_error':repr(exc)})
        page.on('request',request);page.on('response',response);page.goto(BASE,wait_until='domcontentloaded',timeout=60000)
        try:page.wait_for_load_state('networkidle',timeout=15000)
        except Exception:page.wait_for_timeout(4000)
        body=page.locator('body').inner_text(timeout=10000);anchors=page.eval_on_selector_all('a[href]','els=>els.map(a=>({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or []
        # Visit public procurement list first so the normal 24-hour feed is exercised.
        try:
            page.goto('https://zakazky.gov.cz/verejne-zakazky',wait_until='domcontentloaded',timeout=60000)
            try:page.wait_for_load_state('networkidle',timeout=12000)
            except Exception:page.wait_for_timeout(3500)
        except Exception:pass
        # Exercise public search controls only.
        for selector in ('input[placeholder*="zak"]','input[type="search"]','input'):
            loc=page.locator(selector)
            if loc.count():
                try:loc.first.fill('web');page.keyboard.press('Enter');page.wait_for_timeout(3500);break
                except Exception:pass
        after=page.locator('body').inner_text(timeout=8000);after_anchors=page.eval_on_selector_all('a[href]','els=>els.map(a=>({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or []
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
        k=(x['method'],x['url'],x['status'])
        if k not in seen:seen.add(k);network.append(x)
    probe={'source':'CZ_ZAKAZKY_GOV','generated_at':NOW.isoformat(),'body_preview':body[:12000],'after_search_body':after[:12000],'anchors':anchors[:250],'after_search_anchors':after_anchors[:250],'requests':reqs[:400],'network':network[:600],'public_json_samples':samples[:20]}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    good=[x for x in samples if isinstance(x,dict) and x.get('status')==200 and x.get('shape')]
    stats={'source':'CZ_ZAKAZKY_GOV','raw_materialized':0,'current_materialized':0,'probe_only':True,'network_count':len(network),'api_like_count':sum(('api.' in x['url'].lower() or '/api/' in x['url'].lower()) for x in network),'request_count':len(reqs),'public_json_samples':len(good),'generated_at':NOW.isoformat(),'errors':[] if good else [{'type':'NO_PUBLIC_PROCUREMENT_JSON_CAPTURED'}],'official_url':BASE}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2));print(json.dumps(stats,indent=2));print('PUBLIC_JSON',json.dumps(good[:8],ensure_ascii=False,indent=2)[:500000]);print('AFTER',after[:10000]);print('REQUESTS',json.dumps(reqs[:160],ensure_ascii=False,indent=2)[:80000])
    if not good:raise SystemExit(2)
if __name__=='__main__':main()
