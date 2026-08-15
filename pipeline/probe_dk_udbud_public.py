from __future__ import annotations

import json, os, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/DK_UDBUD_PUBLIC'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://udbud.dk/'
SEARCH='https://udbud.dk/soeg?aktuelSide=1&maksElementer=25&sorteringFelt=PUBLIKATION_DATO&sorteringRetning=Desc&formularType=NATIONALE_UDBUD&formularType=EU_UDBUD'
NOW=datetime.now(timezone.utc)

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        s={'source':'DK_UDBUD_PUBLIC','raw_materialized':0,'current_materialized':0,'errors':[{'type':'NO_SYSTEM_CHROME'}]};(OUT/'stats.json').write_text(json.dumps(s,indent=2));raise SystemExit(2)
    from playwright.sync_api import sync_playwright
    pw=browser=context=page=None;net=[];reqs=[];body='';anchors=[];buttons=[]
    try:
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context(locale='da-DK');page=context.new_page()
        def req(r):
            try:
                u=r.url.lower()
                if any(k in u for k in ('soeg','search','udbud','notice','annon','opslag','bekendt')):
                    raw=r.post_data or '';parsed=None
                    try:parsed=json.loads(raw) if raw else None
                    except Exception:parsed=raw[:8000]
                    reqs.append({'url':r.url,'method':r.method,'post_data':parsed})
            except Exception:pass
        def resp(r):
            try:
                ct=(r.headers.get('content-type') or '').lower();u=r.url.lower()
                if 'json' in ct or any(k in u for k in ('soeg','search','notice','procure','annon','opslag','bekendt')):
                    net.append({'url':r.url,'status':r.status,'method':r.request.method,'content_type':ct})
            except Exception:pass
        page.on('request',req);page.on('response',resp)
        page.goto(SEARCH,wait_until='domcontentloaded',timeout=60000)
        try:page.wait_for_load_state('networkidle',timeout=18000)
        except Exception:page.wait_for_timeout(5000)
        body=page.locator('body').inner_text(timeout=10000)
        anchors=page.eval_on_selector_all('a[href]','els => els.map(a => ({href:a.href,text:(a.innerText||a.textContent||"").trim(),class:a.className||""}))') or []
        buttons=page.eval_on_selector_all('button','els => els.map(b => ({text:(b.innerText||b.textContent||"").trim(),aria:b.getAttribute("aria-label"),class:b.className||""}))') or []
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
    tender_links=[a for a in anchors if any(k in str(a.get('href','')).lower() for k in ('udbud/','bekendt','notice','annon','opslag')) and '/soeg' not in str(a.get('href','')).lower()]
    probe={'source':'DK_UDBUD_PUBLIC','generated_at':NOW.isoformat(),'search_url':SEARCH,'body_preview':body[:30000],'anchors':anchors[:500],'buttons':buttons[:150],'requests':reqs[:500],'network':network[:700],'candidate_link_count':len(tender_links),'candidate_links':tender_links[:250]}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'source':'DK_UDBUD_PUBLIC','raw_materialized':0,'current_materialized':0,'probe_only':True,'anchor_count':len(anchors),'candidate_link_count':len(tender_links),'network_count':len(network),'api_like_count':sum('/api/' in x['url'].lower() for x in network),'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'search_url':SEARCH}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2));print(json.dumps(stats,indent=2));print('BODY',body[:18000]);print('REQUESTS',json.dumps(reqs[:200],ensure_ascii=False,indent=2)[:100000]);print('NETWORK',json.dumps(network[:200],ensure_ascii=False,indent=2));print('CANDIDATE_LINKS',json.dumps(tender_links[:120],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
