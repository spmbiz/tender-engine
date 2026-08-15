from __future__ import annotations

import json, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/NO_DOFFIN'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_NOTICES=max(50,min(3000,int(os.getenv('NO_MAX_NOTICES','1200'))));PAGE_SIZE=min(100,int(os.getenv('NO_PAGE_SIZE','100')));ENRICH_MAX=min(MAX_NOTICES,int(os.getenv('NO_DETAIL_MAX','500')))
BASE='https://api.doffin.no/webclient/api/v2';SEARCH=BASE+'/search-api/search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.7 (+public procurement research)','Accept':'application/json','Origin':'https://www.doffin.no','Referer':'https://www.doffin.no/'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None
def buyer_name(v):
    if isinstance(v,list) and v:
        x=v[0]
        if isinstance(x,dict):return clean(x.get('name') or x.get('organizationName')) or None
        return clean(x) or None
    if isinstance(v,dict):return clean(v.get('name') or v.get('organizationName')) or None
    return clean(v) or None
def amount(v):
    if isinstance(v,dict):return v.get('amount'),v.get('currencyCode') or v.get('currency')
    return v,None
def detail(nid):
    try:
        r=S.get(f'{BASE}/notices-api/notices/{requests.utils.quote(nid,safe="")}',timeout=45)
        if r.ok:return r.json()
    except Exception:pass
    return None
def main():
    cutoff=(NOW-timedelta(days=DAYS)).date();raw=[];tele=[];page=1;reached_old=False;enriched=0;accessible=None
    while len(raw)<MAX_NOTICES and not reached_old:
        body={'searchString':'','numHitsPerPage':min(PAGE_SIZE,MAX_NOTICES-len(raw)),'page':page}
        r=S.post(SEARCH,json=body,timeout=60);tele.append({'page':page,'status':r.status_code,'bytes':len(r.content),'body':body});r.raise_for_status();data=r.json();hits=data.get('hits') or []
        if accessible is None:accessible=data.get('numHitsAccessible')
        if not hits:break
        for h in hits:
            if not isinstance(h,dict):continue
            pub=pdt(h.get('publicationDate') or h.get('issueDate') or h.get('publishedDate'))
            if pub and pub.date()<cutoff:reached_old=True;break
            nid=clean(h.get('id') or h.get('doffinId') or h.get('noticeId'))
            if nid and enriched<ENRICH_MAX:
                d=detail(nid);enriched+=1
                if isinstance(d,dict):
                    for k in ('allCpvCodes','directCpvCodes','parentCpvCodes','competitionDocsUrl','tedId','sentToTed','regulationUrl','description','procedureType','submissionUrl','portalUrl'):
                        if h.get(k) in (None,'',[]) and d.get(k) not in (None,'',[]):h[k]=d[k]
                time.sleep(0.03)
            raw.append(h)
            if len(raw)>=MAX_NOTICES:break
        if reached_old or len(hits)<body['numHitsPerPage']:break
        if accessible and page*PAGE_SIZE>=int(accessible):break
        page+=1;time.sleep(0.1)
    rows=[]
    for h in raw:
        nid=clean(h.get('id') or h.get('doffinId') or h.get('noticeId'))
        if not nid:continue
        title=clean(h.get('heading') or h.get('title') or h.get('name') or h.get('noticeTitle'))
        deadline=pdt(h.get('deadline') or h.get('submissionDeadline') or h.get('offerDeadline'))
        pub=pdt(h.get('publicationDate') or h.get('issueDate') or h.get('publishedDate'))
        kind=clean(h.get('type') or h.get('noticeType'));status=clean(h.get('status'))
        lk=f'{kind} {status}'.lower();current=bool((not deadline or deadline>=NOW) and not any(x in lk for x in ('award','result','cancel','closed','inactive','completed')))
        est,currency=amount(h.get('estimatedValue'));kgv=clean(h.get('competitionDocsUrl') or h.get('submissionUrl') or h.get('portalUrl')) or None
        cpv=h.get('allCpvCodes') or h.get('directCpvCodes') or h.get('parentCpvCodes') or h.get('cpvCodes')
        detail_url=f'https://www.doffin.no/notices/{nid}'
        rows.append({'candidate_id':f'NO-DOFFIN:{nid}','source':'NO_DOFFIN','portal':'NO_DOFFIN','notice_id':nid,'title':title or nid,'buyer':buyer_name(h.get('buyer') or h.get('contractingAuthority')),'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':current,'notice_url':detail_url,'estimated_value':est,'currency':currency or 'NOK','description':clean(h.get('description') or h.get('shortDescription')),'cpv':cpv,'notice_type':kind or None,'status':status or None,'ted_id':h.get('tedId'),'route':{'document_urls':[],'detail_url':detail_url,'proceeding_url':kgv,'competition_docs_url':kgv},'discovered_at':NOW.isoformat()})
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'NO_DOFFIN','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'dce_portal_urls':sum(bool((x.get('route') or {}).get('proceeding_url')) for x in rows),'detail_enriched':enriched,'lookback_days':DAYS,'num_hits_accessible':accessible,'generated_at':NOW.isoformat(),'errors':[],'official_url':SEARCH,'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
