from __future__ import annotations

import json, os, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/DK_UDBUD_PUBLIC'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://udbud.dk/'
NOW=datetime.now(timezone.utc)

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        s={'source':'DK_UDBUD_PUBLIC','raw_materialized':0,'current_materialized':0,'errors':[{'type':'NO_SYSTEM_CHROME'}]};(OUT/'stats.json').write_text(json.dumps(s,indent=2));raise SystemExit(2)
    from playwright.sync_api import sync_playwright
    pw=browser=context=page=None;net=[];body='';anchors=[];buttons=[]
    try:
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context(locale='da-DK');page=context.new_page()
        def resp(r):
            try:
                ct=(r.headers.get('content-type') or '').lower();u=r.url.lower()
                if 'json' in ct or '/api/' in u or 'udbud' in u and any(k in u for k in ('search','notice','procure','annon','opslag')):net.append({'url':r.url,'status':r.status,'method':r.request.method,'content_type':ct})
            except Exception:pass
        page.on('response',resp);page.goto(BASE,wait_until='domcontentloaded',timeout=60000)
        try:page.wait_for_load_state('networkidle',timeout=18000)
        except Exception:page.wait_for_timeout(4000)
        body=page.locator('body').inner_text(timeout=10000);anchors=page.eval_on_selector_all('a[href]','els => els.map(a => ({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or [];buttons=page.eval_on_selector_all('button','els => els.map(b => ({text:(b.innerText||b.textContent||"").trim(),aria:b.getAttribute("aria-label")}))') or []
        # Click only obvious public search/navigation controls. Do not touch login/create-account.
        for label in ('Søg udbud','Find udbud','Udbud','Search tenders'):
            loc=page.get_by_text(label,exact=False)
            if loc.count():
                try:loc.first.click(timeout=5000);page.wait_for_timeout(2500);break
                except Exception:pass
        try:
            body2=page.locator('body').inner_text(timeout=7000);anchors2=page.eval_on_selector_all('a[href]','els => els.map(a => ({href:a.href,text:(a.innerText||a.textContent||"").trim()}))') or []
        except Exception:body2='';anchors2=[]
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
    probe={'source':'DK_UDBUD_PUBLIC','generated_at':NOW.isoformat(),'body_preview':body[:12000],'after_navigation_body':body2[:12000],'anchors':anchors[:250],'after_navigation_anchors':anchors2[:250],'buttons':buttons[:100],'network':network[:600]}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'source':'DK_UDBUD_PUBLIC','raw_materialized':0,'current_materialized':0,'probe_only':True,'anchor_count':len(anchors),'network_count':len(network),'api_like_count':sum('/api/' in x['url'].lower() for x in network),'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2));print(json.dumps(stats,indent=2));print('BODY',body[:4000]);print('AFTER',body2[:4000]);print('NETWORK',json.dumps(network[:160],ensure_ascii=False,indent=2));print('ANCHORS',json.dumps((anchors+anchors2)[:160],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
