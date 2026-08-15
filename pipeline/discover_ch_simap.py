from __future__ import annotations

import json, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/CH_SIMAP'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(30,int(os.getenv('LOOKBACK_DAYS','14'))));MAX_PAGES=max(1,min(100,int(os.getenv('CH_MAX_PAGES','40'))));MAX_DETAILS=max(1,min(1500,int(os.getenv('CH_MAX_DETAILS','600'))))
HOST='https://www.simap.ch';SEARCH='/api/publications/v2/project/project-search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.1 (+public procurement research)','Accept':'application/json'})
def clean(v):return ' '.join(str(v or '').split())
def tr(v):
    if isinstance(v,str):return clean(v)
    if isinstance(v,dict):
        for k in ('en','fr','de','it'):
            if v.get(k):return clean(v[k])
    return None
def pdt(v):
    if isinstance(v,dict):v=v.get('dateTime') or v.get('date') or v.get('value')
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return (x if x.tzinfo else x.replace(tzinfo=ZoneInfo('Europe/Zurich'))).astimezone(timezone.utc)
    except Exception:return None
def items(data):return data.get('projects') if isinstance(data,dict) and isinstance(data.get('projects'),list) else []
def detail_dates(d):
    if not isinstance(d,dict):return None
    dates=d.get('dates') or {}
    if not isinstance(dates,dict):return None
    return pdt(dates.get('offerDeadline') or dates.get('participationDeadline') or dates.get('submissionDeadline'))
def is_competition(pubtype,process):
    p=clean(pubtype).lower().replace('-','_').replace(' ','_');pr=clean(process).lower()
    if any(x in p for x in ('award','result','direct_award','advance_notice','revocation','abandonment','cancel','correction')):return False
    if p in ('tender','competition','study_contract','call_for_bids','invitation_to_tender'):return True
    return any(x in p for x in ('tender','competition','call_for_bid')) or (not p and pr in ('open','selective','invitation','negotiated'))
def main():
    from_date=(NOW-timedelta(days=DAYS)).astimezone(ZoneInfo('Europe/Zurich')).date().isoformat()
    q={'newestPublicationFrom':from_date};last=None;rows=[];tele=[];detail_calls=0
    for page in range(MAX_PAGES):
        qq=dict(q)
        if last:qq['lastItem']=last
        r=S.get(HOST+SEARCH,params=qq,timeout=60);tele.append({'page':page,'status':r.status_code,'bytes':len(r.content),'url':r.url,'preview':clean(r.text)[:300] if not r.ok else None});r.raise_for_status();data=r.json();projects=items(data)
        if not projects:break
        for o in projects:
            pid=clean(o.get('id'));pubid=clean(o.get('publicationId'));title=tr(o.get('title'));pubtype=clean(o.get('pubType'));process=clean(o.get('processType'))
            if not (pid or title):continue
            deadline=None;hasdocs=None;detail_url=None;desc='';cpv=None
            if pid and pubid and detail_calls<MAX_DETAILS:
                detail_url=f'{HOST}/api/publications/v1/project/{pid}/publication-details/{pubid}'
                try:
                    dr=S.get(detail_url,timeout=45);detail_calls+=1
                    if dr.ok:
                        details=dr.json();deadline=detail_dates(details);hasdocs=details.get('hasProjectDocuments')
                        # publication-details can refine the publication type; prefer it when available.
                        pubtype=clean(details.get('publicationType') or details.get('pubType') or pubtype)
                        process=clean(details.get('processType') or process)
                        procurement=details.get('procurement') or {}
                        desc=tr(procurement.get('orderDescription')) or ''
                        c=procurement.get('cpvCode') or {};cpv=c.get('code') if isinstance(c,dict) else c
                    else:tele.append({'detail':pid,'status':dr.status_code})
                except Exception as exc:tele.append({'detail':pid,'error':repr(exc)})
                time.sleep(0.02)
            pub=pdt(o.get('publicationDate'));buyer=tr(o.get('procOfficeName'));project_number=clean(o.get('projectNumber'))
            public_page=f'{HOST}/en/project-detail/{pid}' if pid else None;header=f'{HOST}/api/publications/v2/project/{pid}/project-header' if pid else None
            competition=is_competition(pubtype,process);current=bool(competition and (not deadline or deadline>=NOW))
            rows.append({'candidate_id':f'CH-SIMAP:{pid or project_number}','source':'CH_SIMAP','portal':'CH_SIMAP','notice_id':clean(o.get('publicationNumber')) or project_number or pid,'project_id':pid,'publication_id':pubid,'title':title or project_number or pid,'buyer':buyer,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':current,'competition_notice':competition,'notice_url':public_page or detail_url,'description':desc,'cpv':cpv,'process_type':process or None,'publication_type':pubtype or None,'route':{'document_urls':[],'has_project_documents':hasdocs,'project_id':pid,'detail_url':public_page,'header_url':header,'publication_details_url':detail_url,'documents_auth_note':'SIMAP tender documents require tenderer authentication when protected; no bypass'},'discovered_at':NOW.isoformat()})
        pag=data.get('pagination') or {};new_last=pag.get('lastItem') if isinstance(pag,dict) else None
        if not new_last or new_last==last:break
        last=new_last;time.sleep(0.05)
    seen={}
    for x in rows:
        # newest publication for a project wins; result publications can close a previously open project.
        old=seen.get(x['candidate_id'])
        if not old or str(x.get('published') or '')>=str(old.get('published') or ''):seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'CH_SIMAP','raw_materialized':len(rows),'current_materialized':len(cur),'competition_materialized':sum(bool(x['competition_notice']) for x in rows),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'has_project_documents':sum((x.get('route') or {}).get('has_project_documents') is True for x in rows),'lookback_days':DAYS,'detail_calls':detail_calls,'generated_at':NOW.isoformat(),'errors':[],'official_url':HOST+SEARCH,'query':q,'telemetry':tele,'archive':'https://archiv.simap.ch/'}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
