from __future__ import annotations

import json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/GR_KHMDHS'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);LOOKBACK=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(50,int(os.getenv('GR_MAX_PAGES','10'))))
BASE='https://cerpp.eprocurement.gov.gr/khmdhs-opendata'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.4 (+public procurement research)','Accept':'application/json','Content-Type':'application/json'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    for fmt in ('%Y-%m-%d','%Y-%m-%dT%H:%M:%S','%d/%m/%Y','%Y-%m-%d %H:%M:%S'):
        try:return datetime.strptime(s[:19],fmt).replace(tzinfo=timezone.utc)
        except Exception:pass
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None

def val(o,*keys):
    for k in keys:
        if isinstance(o,dict) and o.get(k) not in (None,''):return o.get(k)
    return None

def main():
    date_from=(NOW-timedelta(days=LOOKBACK)).date().isoformat(); date_to=NOW.date().isoformat()
    payload={'dateFrom':date_from,'dateTo':date_to}
    rows=[];tele=[]
    for page in range(MAX_PAGES):
        r=S.post(f'{BASE}/notice',params={'page':page},json=payload,timeout=90)
        tele.append({'page':page,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status();data=r.json()
        content=data.get('content') if isinstance(data,dict) else data
        if not isinstance(content,list):content=[]
        for o in content:
            ref=clean(val(o,'referenceNumber','reference_number','ada','id'))
            title=clean(val(o,'title','subject','description'))
            if not (ref or title):continue
            org=val(o,'organization','contractingAuthority','contractingOrganization')
            if isinstance(org,dict):org=val(org,'value','name','label','key')
            deadline=pdt(val(o,'submissionDate','submissionDeadline','endDate','deadline'))
            signed=pdt(val(o,'signedDate','publicationDate','date'))
            cancelled=bool(val(o,'cancelled','isCancelled','cancellationDate'))
            docs=[]
            if ref:docs=[f'{BASE}/notice/attachment/{requests.utils.quote(ref,safe="")}']
            cost=val(o,'budget','totalCost','estimatedValue','netAmount')
            cpvs=val(o,'cpvItems','cpv','cpvs')
            rows.append({'candidate_id':f'GR-KHMDHS:{ref or abs(hash(title))}','source':'GR_KHMDHS','portal':'GR_KHMDHS','notice_id':ref or None,'title':title or ref,'buyer':clean(org) or None,'deadline':deadline.isoformat() if deadline else None,'published':signed.isoformat() if signed else None,'current':not cancelled and (not deadline or deadline>=NOW),'notice_url':f'https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/{requests.utils.quote(ref,safe="")}' if ref else None,'estimated_value':cost,'currency':'EUR','cpv':cpvs,'description':clean(val(o,'description','comments','title')),'route':{'document_urls':docs,'direct_public_dce':bool(docs)},'discovered_at':NOW.isoformat()})
        if isinstance(data,dict) and (data.get('last') is True or page>=int(data.get('totalPages') or 1)-1):break
        if not content:break
    seen={};
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'GR_KHMDHS','raw_materialized':len(rows),'current_materialized':len(cur),'lookback_days':LOOKBACK,'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'telemetry':tele,'dce_route':'/notice/attachment/{referenceNumber}'}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
