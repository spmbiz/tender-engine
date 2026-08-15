from __future__ import annotations

import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/CH_SIMAP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);MAX_PAGES=max(1,min(30,int(os.getenv('CH_MAX_PAGES','8'))))
HOSTS=['https://www.simap.ch','https://simap.ch']
PATH='/api/publications/v2/project/project-search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.4 (+public procurement research)','Accept':'application/json,*/*'})
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
        for k in ('content','items','projects','results','entries','data'):
            if isinstance(data.get(k),list):return data[k]
    return []
def val(o,*names):
    if not isinstance(o,dict):return None
    low={str(k).lower():v for k,v in o.items()}
    for n in names:
        if n.lower() in low and low[n.lower()] not in (None,''):return low[n.lower()]
    return None

def main():
    chosen=None;first=None;tele=[]
    variants=[{}, {'page':0,'size':100}, {'page':0,'limit':100}, {'pageNumber':0,'pageSize':100}, {'page':0,'size':100,'publicationStates':'published'}]
    for host in HOSTS:
        for q in variants:
            try:r=S.get(host+PATH,params=q,timeout=60);tele.append({'host':host,'query':q,'status':r.status_code,'bytes':len(r.content)})
            except Exception as exc:tele.append({'host':host,'query':q,'error':repr(exc)});continue
            if not r.ok:continue
            try:data=r.json()
            except Exception:continue
            if items(data):chosen=(host,q);first=data;break
        if first is not None:break
    if first is None:
        stats={'source':'CH_SIMAP','raw_materialized':0,'current_materialized':0,'generated_at':NOW.isoformat(),'errors':[{'type':'NO_WORKING_PUBLIC_QUERY','telemetry':tele}],'official_url':HOSTS[0]+PATH}
        (OUT/'stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8');print(json.dumps(stats,indent=2));raise SystemExit(2)
    rows=[];host,q0=chosen
    for page in range(MAX_PAGES):
        if page==0:data=first
        else:
            q=dict(q0);q['page']=page;q.setdefault('size',100)
            try:r=S.get(host+PATH,params=q,timeout=60);tele.append({'page':page,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status();data=r.json()
            except Exception:break
        its=items(data)
        if not its:break
        for o in its:
            if not isinstance(o,dict):continue
            pid=clean(val(o,'projectId','id','projectNumber'))
            title=clean(val(o,'title','projectTitle','name','description'))
            if not (pid or title):continue
            pubtype=clean(val(o,'publicationType','pubType','projectType','projectKind'))
            lpt=pubtype.lower()
            if any(x in lpt for x in ('award','direct_award','advanced_notice')) and 'call' not in lpt:continue
            deadline=pdt(val(o,'offerDeadline','submissionDeadline','deadline','participationRequestDeadline'))
            pub=pdt(val(o,'publicationDate','publishedAt','date'))
            buyer=val(o,'procOfficeName','procurementOfficeName','buyerName','organizationName')
            if isinstance(buyer,dict):buyer=val(buyer,'name','displayName')
            hasdocs=bool(val(o,'hasProjectDocuments','hasDocuments'))
            detail=f'{host}/api/publications/v2/project/{pid}/project-header' if pid else None
            rows.append({'candidate_id':f'CH-SIMAP:{pid or abs(hash(title))}','source':'CH_SIMAP','portal':'CH_SIMAP','notice_id':pid or None,'title':title or pid,'buyer':clean(buyer) or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':not deadline or deadline>=NOW,'notice_url':detail,'description':clean(val(o,'description','shortDescription')),'cpv':val(o,'cpvCode','cpvCodes'),'route':{'document_urls':[],'has_project_documents':hasdocs,'project_id':pid},'publication_type':pubtype or None,'discovered_at':NOW.isoformat()})
        if isinstance(data,dict) and data.get('last') is True:break
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'CH_SIMAP','raw_materialized':len(rows),'current_materialized':len(cur),'generated_at':NOW.isoformat(),'errors':[],'official_url':host+PATH,'chosen_query':q0,'telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
