from __future__ import annotations

import json, os, re, shutil
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/NO_DOFFIN'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    if isinstance(v,dict):v=v.get('dateTime') or v.get('date') or v.get('value')
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None
def lists(o):
    found=[]
    def walk(x,path=''):
        if isinstance(x,list) and len(x)>=2 and all(isinstance(z,dict) for z in x[:min(3,len(x))]):found.append((path,x))
        elif isinstance(x,dict):
            for k,v in x.items():walk(v,f'{path}.{k}' if path else k)
    walk(o);return found
def val(o,*names):
    if not isinstance(o,dict):return None
    low={str(k).lower().replace('_',''):v for k,v in o.items()}
    for n in names:
        v=low.get(n.lower().replace('_',''))
        if v not in (None,''):return v
    return None
def browser_capture():
    from playwright.sync_api import sync_playwright
    telemetry=[];payloads=[];dom=[];chrome=shutil.which('google-chrome') or shutil.which('chromium')
    with sync_playwright() as pw:
        kw={'headless':True}
        if chrome:kw['executable_path']=chrome
        b=pw.chromium.launch(**kw);ctx=b.new_context();page=ctx.new_page()
        def onresp(resp):
            ct=(resp.headers.get('content-type') or '').lower();u=resp.url
            if 'json' not in ct and '/api/' not in u.lower():return
            try:
                if resp.ok:
                    data=resp.json();cands=lists(data)
                    telemetry.append({'url':u,'status':resp.status,'content_type':ct,'candidate_lists':[(p,len(x)) for p,x in cands[:5]]})
                    if cands:payloads.append((u,data))
                else:telemetry.append({'url':u,'status':resp.status,'content_type':ct})
            except Exception:pass
        page.on('response',onresp)
        for u in ('https://www.doffin.no/search','https://www.doffin.no/','https://www.doffin.no/search?status=ACTIVE'):
            try:
                page.goto(u,wait_until='domcontentloaded',timeout=70000);page.wait_for_timeout(5000);dom.append({'url':u,'body':clean(page.locator('body').inner_text(timeout=10000))[:30000]})
                if payloads:break
            except Exception as exc:telemetry.append({'page':u,'error':repr(exc)})
        b.close()
    return payloads,telemetry,dom
def choose_records(data):
    c=lists(data)
    if not c:return []
    def score(item):
        keys=' '.join(str(k).lower() for k in item.keys())
        return sum(w for term,w in [('title',4),('deadline',4),('notice',3),('publication',3),('buyer',2),('organization',2),('cpv',2),('id',1)] if term in keys)
    best=max(c,key=lambda px:(score(px[1][0]) if px[1] else 0,len(px[1])))
    return best[1]
def main():
    payloads,tele,dom=browser_capture();rows=[]
    for api,data in payloads:
        for o in choose_records(data):
            nid=clean(val(o,'noticeId','id','noticeIdentifier','publicationId','doffinId'))
            title=clean(val(o,'title','noticeTitle','name','description','projectTitle'))
            if not (nid or title):continue
            deadline=pdt(val(o,'deadline','submissionDeadline','tenderDeadline','responseDeadline','receiptDeadline'))
            pub=pdt(val(o,'publicationDate','publishedDate','publishedAt','dispatchDate'))
            buyer=val(o,'buyer','buyerName','contractingAuthority','organizationName','organisationName')
            if isinstance(buyer,dict):buyer=val(buyer,'name','organizationName','organisationName')
            kind=clean(val(o,'noticeType','formType','type','publicationType'))
            lk=kind.lower();current=(not deadline or deadline>=NOW) and not any(x in lk for x in ('award','result','contract modification','completion','cancel'))
            url=val(o,'url','noticeUrl','detailUrl','href')
            if isinstance(url,dict):url=val(url,'href','url')
            if not url and nid:url=f'https://www.doffin.no/notices/{nid}'
            if isinstance(url,str) and url.startswith('/'):url='https://www.doffin.no'+url
            route={'document_urls':[],'detail_url':url if isinstance(url,str) else None}
            rid=nid or str(abs(hash((title,str(pub),api))))
            rows.append({'candidate_id':f'NO-DOFFIN:{rid}','source':'NO_DOFFIN','portal':'NO_DOFFIN','notice_id':nid or None,'title':title or rid,'buyer':clean(buyer) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':bool(current),'notice_url':url if isinstance(url,str) else None,'description':clean(val(o,'description','shortDescription','summary')),'cpv':val(o,'cpv','cpvCodes','mainCpv'),'notice_type':kind or None,'route':route,'captured_api':api,'discovered_at':NOW.isoformat()})
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    (OUT/'frontend_capture.json').write_text(json.dumps({'telemetry':tele,'dom':dom,'api_urls':[u for u,_ in payloads]},indent=2,ensure_ascii=False),encoding='utf-8')
    errs=[] if rows else [{'type':'PUBLIC_FRONTEND_API_UNRESOLVED'}]
    stats={'source':'NO_DOFFIN','raw_materialized':len(rows),'current_materialized':len(cur),'generated_at':NOW.isoformat(),'errors':errs,'official_url':'https://www.doffin.no/','captured_api_urls':[u for u,_ in payloads],'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
