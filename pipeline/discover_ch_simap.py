from __future__ import annotations

import json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/CH_SIMAP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);MAX_PAGES=max(1,min(30,int(os.getenv('CH_MAX_PAGES','8'))))
HOST='https://www.simap.ch';PATH='/api/publications/v2/project/project-search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.6 (+public procurement research)','Accept':'application/json,*/*'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    if isinstance(v,dict):v=v.get('dateTime') or v.get('date') or v.get('value')
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None
def items(data):
    if isinstance(data,list):return data
    if isinstance(data,dict):
        for k in ('content','items','projects','results','entries','data','list'):
            if isinstance(data.get(k),list):return data[k]
    return []
def val(o,*names):
    if not isinstance(o,dict):return None
    low={str(k).lower():v for k,v in o.items()}
    for n in names:
        if n.lower() in low and low[n.lower()] not in (None,''):return low[n.lower()]
    return None

def browser_capture(tele):
    """Use the official anonymous frontend itself to reveal the exact public API call.
    This is a fallback, not an access-control bypass: only responses available to an
    unauthenticated browser session are used.
    """
    from playwright.sync_api import sync_playwright
    captured=[]; dom=[]
    chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    with sync_playwright() as pw:
        kw={'headless':True}
        if chrome:kw['executable_path']=chrome
        browser=pw.chromium.launch(**kw);ctx=browser.new_context();page=ctx.new_page()
        def onresp(resp):
            if 'project-search' not in resp.url:return
            try:
                if resp.ok:
                    data=resp.json()
                    if items(data):captured.append((resp.url,data))
                tele.append({'browser_api_url':resp.url,'browser_api_status':resp.status})
            except Exception as exc:tele.append({'browser_api_url':resp.url,'browser_api_status':resp.status,'parse_error':repr(exc)})
        page.on('response',onresp)
        urls=[
          HOST+'/en?newestPubTypes=%5B%22call_for_bids%22%5D',
          HOST+'/fr?newestPubTypes=%5B%22call_for_bids%22%5D&orderAddressCountryOnlySwitzerland=true',
          HOST+'/en?search=%22service%22&newestPubTypes=%5B%22call_for_bids%22%5D',
        ]
        for u in urls:
            try:
                page.goto(u,wait_until='domcontentloaded',timeout=70000);page.wait_for_timeout(4500)
                dom.append({'url':u,'title':page.title(),'body':clean(page.locator('body').inner_text(timeout=10000))[:20000]})
                if captured:break
            except Exception as exc:tele.append({'browser_url':u,'error':repr(exc)})
        browser.close()
    return captured,dom

def emit_rows(datas,tele):
    rows=[]
    for source_url,data in datas:
        for o in items(data):
            if not isinstance(o,dict):continue
            pid=clean(val(o,'projectId','id','projectNumber'));title=clean(val(o,'title','projectTitle','name','description'))
            if not (pid or title):continue
            pubtype=clean(val(o,'publicationType','pubType','projectType','projectKind','newestPubType'));lpt=pubtype.lower()
            if any(x in lpt for x in ('award','direct_award','advanced_notice')) and 'call' not in lpt:continue
            deadline=pdt(val(o,'offerDeadline','submissionDeadline','deadline','participationRequestDeadline'));pub=pdt(val(o,'publicationDate','publishedAt','date','newestPublicationDate'))
            buyer=val(o,'procOfficeName','procurementOfficeName','buyerName','organizationName','procOffice')
            if isinstance(buyer,dict):buyer=val(buyer,'name','displayName','companyName')
            hasdocs=bool(val(o,'hasProjectDocuments','hasDocuments'))
            public_page=f'{HOST}/en/project-detail/{pid}' if pid else None;header=f'{HOST}/api/publications/v2/project/{pid}/project-header' if pid else None
            rows.append({'candidate_id':f'CH-SIMAP:{pid or abs(hash(title))}','source':'CH_SIMAP','portal':'CH_SIMAP','notice_id':pid or None,'title':title or pid,'buyer':clean(buyer) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':not deadline or deadline>=NOW,'notice_url':public_page or header,'description':clean(val(o,'description','shortDescription')),'cpv':val(o,'cpvCode','cpvCodes'),'route':{'document_urls':[],'has_project_documents':hasdocs,'project_id':pid,'detail_url':public_page or header,'header_url':header},'publication_type':pubtype or None,'api_source_url':source_url,'discovered_at':NOW.isoformat()})
    return rows

def main():
    tele=[];datas=[]
    # Cheap direct probes first; exact frontend network call is fallback.
    for q in ({'newestPubTypes':'call_for_bids'},{'newestPubTypes':'["call_for_bids"]'},{'search':'service','newestPubTypes':'call_for_bids'}):
        r=S.get(HOST+PATH,params=q,timeout=45);tele.append({'query':q,'status':r.status_code,'bytes':len(r.content),'preview':clean(r.text)[:220] if not r.ok else None})
        if r.ok:
            try:data=r.json()
            except Exception:data=None
            if data and items(data):datas.append((r.url,data));break
    dom=[]
    if not datas:
        captured,dom=browser_capture(tele);datas.extend(captured)
    rows=emit_rows(datas,tele)
    # Last-resort DOM evidence is retained for adapter development; it is never promoted as structured notices without IDs.
    (OUT/'frontend_capture.json').write_text(json.dumps({'telemetry':tele,'dom':dom,'captured_urls':[u for u,_ in datas]},indent=2,ensure_ascii=False),encoding='utf-8')
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    errs=[] if rows else [{'type':'PUBLIC_FRONTEND_API_UNRESOLVED','captured_urls':[u for u,_ in datas]}]
    stats={'source':'CH_SIMAP','raw_materialized':len(rows),'current_materialized':len(cur),'generated_at':NOW.isoformat(),'errors':errs,'official_url':HOST+PATH,'captured_api_urls':[u for u,_ in datas],'telemetry':tele,'archive':'https://archiv.simap.ch/'}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
