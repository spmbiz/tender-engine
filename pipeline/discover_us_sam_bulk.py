from __future__ import annotations

import csv, io, json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/US_SAM_BULK')); OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
URL=os.getenv('SAM_BULK_URL','https://s3.amazonaws.com/falextracts/Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv')
S=requests.Session(); S.headers.update({'User-Agent':'Tender-Engine/4.8 (+public procurement research)','Accept':'text/csv,*/*'})
def clean(v): return ' '.join(str(v or '').split())
def first(row,*names):
    lower={str(k).strip().lower():v for k,v in row.items()}
    for n in names:
        v=lower.get(n.lower())
        if v not in (None,''): return clean(v)
    return None
def pdt(v):
    s=clean(v)
    if not s:return None
    for fmt in ('%m/%d/%Y','%m/%d/%Y %H:%M','%Y-%m-%d','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S.%f%z'):
        try:
            x=datetime.strptime(s.replace('Z','+0000'),fmt)
            if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
            return x.astimezone(timezone.utc)
        except Exception:pass
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'))
        if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:return None
def main():
    r=S.get(URL,timeout=180);r.raise_for_status();text=r.content.decode('utf-8-sig',errors='replace');lines=text.splitlines();hi=0
    for i,line in enumerate(lines[:20]):
        low=line.lower()
        if ('noticeid' in low or 'notice id' in low) and ('title' in low or 'solicitation' in low):hi=i;break
    reader=csv.DictReader(io.StringIO('\n'.join(lines[hi:])));rows=[];headers=reader.fieldnames or []
    for row in reader:
        nid=first(row,'NoticeId','Notice ID','notice_id','Id');sol=first(row,'SolicitationNumber','Solicitation Number','Solicitation #');title=first(row,'Title','Opportunity Title','Description')
        if not (nid or sol or title):continue
        deadline=pdt(first(row,'ResponseDeadLine','Response Date','ResponseDate','ArchiveDate','Archive Date'));posted=pdt(first(row,'PostedDate','Posted Date','Publish Date'));active=first(row,'Active','Status','Archive Type')
        current=bool((not deadline or deadline>=NOW) and (not active or active.lower() not in ('false','archived','cancelled','canceled','inactive')))
        rid=nid or sol or re.sub(r'\W+','_',title or '')[:80];notice_url=first(row,'Link','SAM.gov URL','URL') or (f'https://sam.gov/opp/{nid}/view' if nid else None);additional=first(row,'AdditionalInfoLink','Additional Info Link','AdditionalInfo')
        docs=[]
        for k,v in row.items():
            sv=clean(v)
            if sv.startswith('http') and (re.search(r'\.(pdf|zip|docx?|xlsx?|xls|pptx?)(?:\?|$)',sv,re.I) or 'attachment' in str(k).lower()):docs.append(sv)
        rows.append({'candidate_id':f'US-SAM:{rid}','source':'US_SAM_BULK','portal':'US_SAM','notice_id':nid or sol,'solicitation_number':sol,'title':title or sol or rid,'buyer':first(row,'FullParentPathName','Full Parent Path Name','Department/Ind.Agency','Department','Agency','OrganizationName'),'deadline':deadline.isoformat() if deadline else None,'published':posted.isoformat() if posted else None,'current':current,'notice_url':notice_url,'description':first(row,'Description','AdditionalInfo','Additional Info'),'naics':first(row,'NaicsCode','NAICS Code'),'set_aside':first(row,'SetASide','Set Aside'),'type':first(row,'Type','Notice Type'),'route':{'document_urls':list(dict.fromkeys(docs)),'detail_url':notice_url,'additional_info_url':additional},'discovered_at':NOW.isoformat()})
    current=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',current)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'US_SAM_BULK','raw_materialized':len(rows),'current_materialized':len(current),'dce_direct_urls':sum(bool((x.get('route') or {}).get('document_urls')) for x in rows),'additional_info_urls':sum(bool((x.get('route') or {}).get('additional_info_url')) for x in rows),'generated_at':NOW.isoformat(),'errors':[],'official_url':URL,'download_bytes':len(r.content),'headers':headers}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
