from __future__ import annotations

import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/PL_BZP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(100,int(os.getenv('PL_MAX_PAGES','20'))))
BASES=['https://ezamowienia.gov.pl/mo-client-board/api/notices/','https://dev.ezamowienia.gov.pl/mo-board/api/v1/notice','https://ezamowienia.gov.pl/mo-board/api/v1/notice']
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.5 (+public procurement research)','Accept':'application/json,*/*'})
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
        for k in ('content','items','notices','results','data','value','list','result'):
            v=data.get(k)
            if isinstance(v,list):return v
            if isinstance(v,dict):
                for k2 in ('content','items','notices','results','data'):
                    if isinstance(v.get(k2),list):return v[k2]
    return []
def main():
    df=(NOW-timedelta(days=DAYS)).date().isoformat();dt=NOW.date().isoformat()
    variants=[
      {'PublicationDateFrom':df,'PublicationDateTo':dt,'PageSize':100}, {'publicationDateFrom':df,'publicationDateTo':dt,'pageSize':100},
      {'dateFrom':df,'dateTo':dt,'pageSize':100}, {'publicationDateFrom':df,'publicationDateTo':dt},
      {'PageNumber':0,'PageSize':100}, {'page':0,'size':100}, {},
    ]
    first_data=None;chosen=None;tele=[]
    for base in BASES:
        for params in variants:
            try:r=S.get(base,params=params,timeout=60)
            except Exception as exc:tele.append({'base':base,'probe':params,'error':repr(exc)});continue
            t={'base':base,'probe':params,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'preview':clean(r.text)[:450]};tele.append(t)
            if not r.ok:continue
            try:data=r.json();t['json_keys']=list(data.keys()) if isinstance(data,dict) else None
            except Exception:continue
            if extract_items(data):first_data=data;chosen=(base,params);break
        if first_data is not None:break
    if first_data is None:
        stats={'source':'PL_BZP','raw_materialized':0,'current_materialized':0,'generated_at':NOW.isoformat(),'errors':[{'type':'NO_WORKING_QUERY','telemetry':tele}],'official_urls':BASES}
        (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False));raise SystemExit(2)
    rows=[];base,chosen_params=chosen
    for page in range(MAX_PAGES):
        if page==0:data=first_data
        else:
            params=dict(chosen_params or {});params.update({'page':page,'PageNumber':page})
            try:r=S.get(base,params=params,timeout=60);tele.append({'page':page,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status();data=r.json()
            except Exception:break
        its=extract_items(data)
        if not its:break
        for o in its:
            if not isinstance(o,dict):continue
            nid=clean(val(o,'id','noticeId','objectId','bzpNumber','noticeNumber'));num=clean(val(o,'noticeNumber','bzpNumber','number'))
            title=clean(val(o,'title','orderName','name','subject'))
            if not (nid or num or title):continue
            notice_type=clean(val(o,'noticeType','noticeTypeName','type','noticeKind'));lt=notice_type.lower()
            if any(x in lt for x in ('wyniku','result','award','wykonaniu','intent','o zmianie umowy')):continue
            pub=pdt(val(o,'publicationDate','publishedDate','publicationDateTime'));deadline=pdt(val(o,'submissionDeadline','offerDeadline','deadline','tenderDeadline'))
            oid=nid or num or str(abs(hash((title,str(pub)))));detail=f'https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{nid}' if nid else None
            proceeding=clean(val(o,'procedureUrl','proceedingUrl','website','url'))
            rows.append({'candidate_id':f'PL-BZP:{oid}','source':'PL_BZP','portal':'PL_EZAMOWIENIA','notice_id':num or nid,'title':title or oid,'buyer':clean(val(o,'organizationName','contractingAuthorityName','buyerName')) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':not deadline or deadline>=NOW,'notice_url':detail or proceeding,'description':clean(val(o,'description','shortDescription')),'procurement_method':clean(val(o,'procedureType','procedureName')) or None,'route':{'document_urls':[],'proceeding_url':proceeding or None,'detail_url':detail},'discovered_at':NOW.isoformat()})
        if isinstance(data,dict) and data.get('last') is True:break
        if page>0 and len(its)<5:break
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'PL_BZP','raw_materialized':len(rows),'current_materialized':len(cur),'lookback_days':DAYS,'generated_at':NOW.isoformat(),'errors':[],'official_url':base,'chosen_query':chosen_params,'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
