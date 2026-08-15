from __future__ import annotations

import json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/PL_BZP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(100,int(os.getenv('PL_MAX_PAGES','20'))))
BASE='https://ezamowienia.gov.pl/mo-client-board/api/notices/'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.4 (+public procurement research)','Accept':'application/json,*/*'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None

def val(o,*names):
    if not isinstance(o,dict):return None
    lower={str(k).lower().replace('_',''):v for k,v in o.items()}
    for n in names:
        v=lower.get(n.lower().replace('_',''))
        if v not in (None,''):return v
    return None

def extract_items(data):
    if isinstance(data,list):return data
    if isinstance(data,dict):
        for k in ('content','items','notices','results','data','value'):
            v=data.get(k)
            if isinstance(v,list):return v
    return []

def main():
    df=(NOW-timedelta(days=DAYS)).date().isoformat();dt=NOW.date().isoformat()
    variants=[
      {'PublicationDateFrom':df,'PublicationDateTo':dt,'PageSize':100},
      {'publicationDateFrom':df,'publicationDateTo':dt,'pageSize':100},
      {'dateFrom':df,'dateTo':dt,'pageSize':100},
      {'PublicationDateFrom':df,'PublicationDateTo':dt},
      {},
    ]
    first_data=None;chosen=None;tele=[]
    for params in variants:
        try:r=S.get(BASE,params=params,timeout=90);tele.append({'probe':params,'status':r.status_code,'bytes':len(r.content)})
        except Exception as exc:tele.append({'probe':params,'error':repr(exc)});continue
        if not r.ok:continue
        try:data=r.json()
        except Exception:continue
        if extract_items(data):first_data=data;chosen=params;break
    if first_data is None:
        stats={'source':'PL_BZP','raw_materialized':0,'current_materialized':0,'generated_at':NOW.isoformat(),'errors':[{'type':'NO_WORKING_QUERY','telemetry':tele}],'official_url':BASE}
        (OUT/'stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8');print(json.dumps(stats,indent=2));raise SystemExit(2)
    rows=[]
    for page in range(MAX_PAGES):
        if page==0:data=first_data
        else:
            params=dict(chosen or {});params.update({'page':page,'PageNumber':page})
            try:r=S.get(BASE,params=params,timeout=90);tele.append({'page':page,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status();data=r.json()
            except Exception:break
        items=extract_items(data)
        if not items:break
        for o in items:
            if not isinstance(o,dict):continue
            nid=clean(val(o,'id','noticeId','objectId','bzpNumber','noticeNumber'))
            num=clean(val(o,'noticeNumber','bzpNumber','number'))
            title=clean(val(o,'title','orderName','name','subject'))
            if not (nid or num or title):continue
            notice_type=clean(val(o,'noticeType','noticeTypeName','type','noticeKind'))
            lt=notice_type.lower()
            if any(x in lt for x in ('wyniku','result','award','wykonaniu','intent')):continue
            pub=pdt(val(o,'publicationDate','publishedDate','publicationDateTime'))
            deadline=pdt(val(o,'submissionDeadline','offerDeadline','deadline','tenderDeadline'))
            if pub and pub < NOW-timedelta(days=DAYS) and deadline and deadline<NOW:continue
            oid=nid or num or str(abs(hash((title,str(pub)))))
            detail=f'https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{nid}' if nid else None
            proceeding=clean(val(o,'procedureUrl','proceedingUrl','website','url'))
            rows.append({'candidate_id':f'PL-BZP:{oid}','source':'PL_BZP','portal':'PL_EZAMOWIENIA','notice_id':num or nid,'title':title or oid,'buyer':clean(val(o,'organizationName','contractingAuthorityName','buyerName')) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':not deadline or deadline>=NOW,'notice_url':detail or proceeding,'description':clean(val(o,'description','shortDescription')),'procurement_method':clean(val(o,'procedureType','procedureName')) or None,'route':{'document_urls':[],'proceeding_url':proceeding or None},'discovered_at':NOW.isoformat()})
        last=bool(data.get('last')) if isinstance(data,dict) else False
        total_pages=data.get('totalPages') if isinstance(data,dict) else None
        if last or (isinstance(total_pages,int) and page+1>=total_pages):break
        if page>0 and len(items)<10:break
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'PL_BZP','raw_materialized':len(rows),'current_materialized':len(cur),'lookback_days':DAYS,'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'chosen_query':chosen,'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
