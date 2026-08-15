from __future__ import annotations

import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/PL_BZP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(100,int(os.getenv('PL_MAX_PAGES','40'))))
BASE='https://ezamowienia.gov.pl/mo-board/api/v1/notice'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.6 (+public procurement research)','Accept':'application/json,*/*'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None
def val(o,*names):
    if not isinstance(o,dict):return None
    low={str(k).lower().replace('_',''):v for k,v in o.items()}
    for n in names:
        v=low.get(n.lower().replace('_',''))
        if v not in (None,''):return v
    return None
def extract(data):
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
    df=(NOW-timedelta(days=DAYS)).strftime('%Y-%m-%dT00:00:00Z');dt=NOW.strftime('%Y-%m-%dT23:59:59Z')
    baseq={'NoticeType':'ContractNotice','PublicationDateFrom':df,'PublicationDateTo':dt,'PageSize':1000}
    rows=[];tele=[]
    for page in range(MAX_PAGES):
        q=dict(baseq)
        if page:q['PageNumber']=page
        r=S.get(BASE,params=q,timeout=90)
        tele.append({'page':page,'status':r.status_code,'bytes':len(r.content),'x_pagination':r.headers.get('X-Pagination'),'preview':clean(r.text)[:250] if not r.ok else None})
        if not r.ok:
            # Some deployments only accept pageNumber/PageSize or no explicit page 0.
            if page==0:
                q['PageNumber']=0;r=S.get(BASE,params=q,timeout=90);tele.append({'page':0,'retry':True,'status':r.status_code,'bytes':len(r.content),'x_pagination':r.headers.get('X-Pagination'),'preview':clean(r.text)[:250] if not r.ok else None})
            r.raise_for_status()
        data=r.json();its=extract(data)
        if not its:break
        for o in its:
            if not isinstance(o,dict):continue
            nid=clean(val(o,'id','noticeId','objectId'));num=clean(val(o,'noticeNumber','bzpNumber','number'))
            title=clean(val(o,'title','orderName','name','subject'))
            if not (nid or num or title):continue
            pub=pdt(val(o,'publicationDate','publishedDate','publicationDateTime'));deadline=pdt(val(o,'submissionDeadline','offerDeadline','deadline','tenderDeadline'))
            oid=nid or num or str(abs(hash((title,str(pub)))))
            detail=f'https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{nid}' if nid else None
            proceeding=clean(val(o,'procedureUrl','proceedingUrl','website','url')) or None
            rows.append({'candidate_id':f'PL-BZP:{oid}','source':'PL_BZP','portal':'PL_EZAMOWIENIA','notice_id':num or nid,'title':title or oid,'buyer':clean(val(o,'organizationName','contractingAuthorityName','buyerName')) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':not deadline or deadline>=NOW,'notice_url':detail or proceeding,'description':clean(val(o,'description','shortDescription')),'procurement_method':clean(val(o,'procedureType','procedureName')) or None,'route':{'document_urls':[],'proceeding_url':proceeding,'detail_url':detail},'discovered_at':NOW.isoformat()})
        xp=r.headers.get('X-Pagination')
        if xp:
            try:
                meta=json.loads(xp)
                total=int(meta.get('TotalPages') or meta.get('totalPages') or 1)
                if page+1>=total:break
            except Exception:pass
        if len(its)<1000:break
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'PL_BZP','raw_materialized':len(rows),'current_materialized':len(cur),'lookback_days':DAYS,'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'query':baseq,'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
