from __future__ import annotations

import json, os, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/PL_BZP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(100,int(os.getenv('PL_MAX_PAGES','40'))))
BASE='https://ezamowienia.gov.pl/mo-board/api/v1/notice'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.7 (+public procurement research)','Accept':'application/json,*/*'})
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
    return []
def extract_proceeding_url(o):
    # Some API rows already expose the procedure/OCID URL; otherwise the public notice HTML is the resolver source.
    for k in ('procedureUrl','proceedingUrl','website','url','tenderUrl'):
        x=val(o,k)
        if isinstance(x,str) and x.startswith('http'):return clean(x)
    for x in o.values() if isinstance(o,dict) else []:
        if isinstance(x,str):
            m=re.search(r'https?://ezamowienia\.gov\.pl/mp-client/search/list/ocds-[A-Za-z0-9-]+',x)
            if m:return m.group(0)
    return None
def main():
    df=(NOW-timedelta(days=DAYS)).date().isoformat();dt=NOW.date().isoformat();page_size=500
    rows=[];tele=[];search_after=None
    for page_idx in range(MAX_PAGES):
        q={'NoticeType':'ContractNotice','PublicationDateFrom':df,'PublicationDateTo':dt,'PageSize':page_size}
        if search_after:q['SearchAfter']=search_after
        ok=None
        for attempt in range(4):
            r=S.get(BASE,params=q,timeout=90)
            tele.append({'page':page_idx,'attempt':attempt+1,'status':r.status_code,'bytes':len(r.content),'search_after':search_after,'preview':clean(r.text)[:250] if not r.ok else None})
            if r.ok:ok=r;break
            if r.status_code not in (429,500,502,503,504):break
            time.sleep(2**attempt)
        if ok is None:
            if not rows:
                stats={'source':'PL_BZP','raw_materialized':0,'current_materialized':0,'lookback_days':DAYS,'generated_at':NOW.isoformat(),'errors':[{'type':'API_QUERY_FAILED','telemetry':tele}],'official_url':BASE,'query':q};(OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False));raise SystemExit(2)
            break
        data=ok.json();its=extract(data)
        if not its:break
        for o in its:
            if not isinstance(o,dict):continue
            object_id=clean(val(o,'objectId','id','noticeId'));num=clean(val(o,'noticeNumber','bzpNumber','number'))
            title=clean(val(o,'title','orderName','name','subject'))
            if not (object_id or num or title):continue
            pub=pdt(val(o,'publicationDate','publishedDate','publicationDateTime'));deadline=pdt(val(o,'submissionDeadline','offerDeadline','deadline','tenderDeadline'))
            oid=object_id or num or str(abs(hash((title,str(pub)))))
            detail=f'https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{object_id}' if object_id else (f'https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/{requests.utils.quote(num,safe="")}' if num else None)
            proceeding=extract_proceeding_url(o)
            desc=clean(val(o,'description','shortDescription','htmlBody','content'))
            if not proceeding and desc:
                m=re.search(r'https?://ezamowienia\.gov\.pl/mp-client/search/list/ocds-[A-Za-z0-9-]+',desc)
                if m:proceeding=m.group(0)
            rows.append({'candidate_id':f'PL-BZP:{oid}','source':'PL_BZP','portal':'PL_EZAMOWIENIA','notice_id':num or object_id,'object_id':object_id or None,'title':title or oid,'buyer':clean(val(o,'organizationName','contractingAuthorityName','buyerName')) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':not deadline or deadline>=NOW,'notice_url':detail or proceeding,'description':desc,'procurement_method':clean(val(o,'procedureType','procedureName')) or None,'route':{'document_urls':[],'proceeding_url':proceeding,'detail_url':detail},'raw_keys':sorted(o.keys()),'discovered_at':NOW.isoformat()})
        if len(its)<page_size:break
        next_after=clean(val(its[-1],'objectId'))
        if not next_after or next_after==search_after:break
        search_after=next_after;time.sleep(0.1)
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'PL_BZP','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'proceeding_urls':sum(bool((x.get('route') or {}).get('proceeding_url')) for x in rows),'lookback_days':DAYS,'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'query':{'NoticeType':'ContractNotice','PublicationDateFrom':df,'PublicationDateTo':dt,'PageSize':page_size},'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
