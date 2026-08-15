from __future__ import annotations

import json, os, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/CZ_ZAKAZKY_GOV'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://zakazky.gov.cz/'
NOW=datetime.now(timezone.utc)

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        s={'source':'CZ_ZAKAZKY_GOV','raw_materialized':0,'current_materialized':0,'errors':[{'type':'NO_SYSTEM_CHROME'}]};(OUT/'stats.json').write_text(json.dumps(s,indent=2));raise SystemExit(2)
    from playwright.sync_api import sync_playwright
    pw=browser=context=page=None;net=[];reqs=[];body='';anchors=[]
    try:
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context(locale='cs-CZ');page=context.new_page()
        def request(r):
            try:
                u=r.url.lower()
                if '/api/' in u or any(k in u for k in ('zakazk','search','tender','procurement')):
                    raw=r.post_data or '';parsed=None
                    try:parsed=json.loads(raw) if raw else None
                    except Exception:parsed=raw[:6000]
                    reqs.append({'url':r.url,'method':r.method,'post_data':parsed})
            except Exception:pass
        def response(r):
            try:
                ct=(r.headers.get('content-type') or '').lower();u=r.url.lower()
                if 'json' in ct or '/api/' in u or any(k in u for k in ('search','zakazk','tender')):net.append({'url':r.url,'status':r.status,'method':r.request.method,'content_type':ct})
            except Exception:pass
        page.on('request',request);page.on('response',response);page.goto(BASE,wait_until='domcontentloaded',timeout=60000)
        try:page.wait_for_load_state('networkidle',timeout=15000)
        except Exception:page.wait_for_timeout(4000)
        body=page.locator('body').inner_text(timeout=10000);anchors=page.eval_on_selector_all('a[href]','els=>els.map(a=>({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or []
        # Exercise only public search controls if present.
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
    probe={'source':'CZ_ZAKAZKY_GOV','generated_at':NOW.isoformat(),'body_preview':body[:12000],'after_search_body':after[:12000],'anchors':anchors[:250],'after_search_anchors':after_anchors[:250],'requests':reqs[:400],'network':network[:600]}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'source':'CZ_ZAKAZKY_GOV','raw_materialized':0,'current_materialized':0,'probe_only':True,'network_count':len(network),'api_like_count':sum('/api/' in x['url'].lower() for x in network),'request_count':len(reqs),'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2));print(json.dumps(stats,indent=2));print('BODY',body[:3000]);print('AFTER',after[:5000]);print('REQUESTS',json.dumps(reqs[:120],ensure_ascii=False,indent=2)[:40000]);print('NETWORK',json.dumps(network[:120],ensure_ascii=False,indent=2)[:40000])
if __name__=='__main__':main()
