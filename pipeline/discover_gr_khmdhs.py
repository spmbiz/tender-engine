from __future__ import annotations

import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/GR_KHMDHS'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);LOOKBACK=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(100,int(os.getenv('GR_MAX_PAGES','30'))))
BASE='https://cerpp.eprocurement.gov.gr/khmdhs-opendata'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.5 (+public procurement research)','Accept':'application/json','Content-Type':'application/json'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:pass
    for fmt in ('%Y-%m-%d %H:%M','%Y-%m-%d','%d/%m/%Y'):
        try:return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc)
        except Exception:pass
    return None
def kv(v):
    if isinstance(v,dict):return v.get('value') or v.get('name') or v.get('label') or v.get('key')
    return v
def cpvs(o):
    out=[]
    for d in o.get('objectDetails') or []:
        for c in d.get('cpvs') or []:
            x=kv(c)
            if x:out.append(clean(x))
    return list(dict.fromkeys(out))
def main():
    date_from=(NOW-timedelta(days=LOOKBACK)).date().isoformat();date_to=NOW.date().isoformat()
    payload={'dateFrom':date_from,'dateTo':date_to,'isModified':False}
    rows=[];tele=[];sample_keys=[]
    for page in range(MAX_PAGES):
        r=S.post(f'{BASE}/notice',params={'page':page},json=payload,timeout=90);tele.append({'page':page,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status();data=r.json()
        content=data.get('content') if isinstance(data,dict) else data
        if not isinstance(content,list):content=[]
        if content and not sample_keys:sample_keys=sorted(content[0].keys())
        for o in content:
            ref=clean(o.get('referenceNumber'));title=clean(o.get('title'))
            if not (ref or title):continue
            deadline=pdt(o.get('finalSubmissionDate'))
            submitted=pdt(o.get('submissionDate'));published=pdt(o.get('publishedDate')) or submitted or pdt(o.get('signedDate'))
            cancelled=bool(o.get('cancelled') or o.get('cancellationDate'))
            org=kv(o.get('organization'))
            if not org and isinstance(o.get('contractingData'),dict):org=kv(o['contractingData'].get('unitsOperator'))
            cost=o.get('totalCostWithoutVAT')
            if cost in (None,''):cost=o.get('budget')
            website=clean(o.get('biddingWebsite')) or None
            docs=[f'{BASE}/notice/attachment/{requests.utils.quote(ref,safe="")}'] if ref else []
            detail=f'https://cerpp.eprocurement.gov.gr/upgkimdis/unprotected/home.xhtml?referenceNumber={requests.utils.quote(ref,safe="")}' if ref else None
            rows.append({'candidate_id':f'GR-KHMDHS:{ref or abs(hash(title))}','source':'GR_KHMDHS','portal':'GR_KHMDHS','notice_id':ref or None,'title':title or ref,'buyer':clean(org) or None,'deadline':deadline.isoformat() if deadline else None,'published':published.isoformat() if published else None,'current':not cancelled and (not deadline or deadline>=NOW),'notice_url':detail,'estimated_value':cost,'currency':'EUR','cpv':cpvs(o),'description':' | '.join(clean(d.get('shortDescription')) for d in o.get('objectDetails') or [] if d.get('shortDescription')),'procedure':clean(kv(o.get('typeOfProcedure'))) or None,'contract_type':clean(kv(o.get('contractType'))) or None,'notice_type':clean(kv(o.get('noticeType'))) or None,'route':{'document_urls':docs,'direct_public_dce':bool(docs),'detail_url':detail,'proceeding_url':website},'discovered_at':NOW.isoformat()})
        if isinstance(data,dict) and (data.get('last') is True or page>=int(data.get('totalPages') or 1)-1):break
        if not content:break
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'GR_KHMDHS','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'buyer_parsed':sum(bool(x['buyer']) for x in rows),'lookback_days':LOOKBACK,'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'telemetry':tele,'dce_route':'/notice/attachment/{referenceNumber}','sample_keys':sample_keys}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
