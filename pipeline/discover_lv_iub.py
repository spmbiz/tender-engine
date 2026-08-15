from __future__ import annotations

import json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/LV_IUB'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);DAYS=max(1,min(45,int(os.getenv('LOOKBACK_DAYS','14'))))
BASE='https://open.iub.gov.lv/data/notice'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.4 (+public procurement research)','Accept':'application/json,*/*'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:pass
    for fmt in ('%Y-%m-%d','%d.%m.%Y','%d/%m/%Y','%Y-%m-%d %H:%M:%S'):
        try:return datetime.strptime(s[:19],fmt).replace(tzinfo=timezone.utc)
        except Exception:pass
    return None

def walk_values(o,keyparts):
    out=[]
    if isinstance(o,dict):
        for k,v in o.items():
            lk=str(k).lower()
            if any(p in lk for p in keyparts) and not isinstance(v,(dict,list)) and v not in (None,''):out.append(v)
            out.extend(walk_values(v,keyparts))
    elif isinstance(o,list):
        for v in o:out.extend(walk_values(v,keyparts))
    return out

def first(o,*parts):
    xs=walk_values(o,tuple(p.lower() for p in parts));return clean(xs[0]) if xs else None

def iter_notices(data):
    if isinstance(data,list):
        for x in data:
            if isinstance(x,dict):yield x
    elif isinstance(data,dict):
        for k in ('notices','items','data','results','content'):
            v=data.get(k)
            if isinstance(v,list):
                for x in v:
                    if isinstance(x,dict):yield x
                return
        yield data

def main():
    rows=[];tele=[]
    for ago in range(DAYS):
        d=(NOW-timedelta(days=ago)).date();url=f'{BASE}/{d.year:04d}/{d.month:02d}/{d.day:02d}-{d.month:02d}-{d.year:04d}.json'
        try:r=S.get(url,timeout=90)
        except Exception as exc:tele.append({'date':d.isoformat(),'error':repr(exc)});continue
        tele.append({'date':d.isoformat(),'status':r.status_code,'bytes':len(r.content),'url':url})
        if r.status_code==404:continue
        try:r.raise_for_status();data=r.json()
        except Exception:continue
        for o in iter_notices(data):
            nid=first(o,'noticeidentifier','noticeid','publicationnumber','id') or clean(o.get('id') if isinstance(o,dict) else '')
            title=first(o,'title','procurementtitle','contracttitle','subject','name')
            if not (nid or title):continue
            ntype=(first(o,'noticetype','formtype','subtype','notice-type') or '').lower()
            # exclude clear award/result/planning publications; keep competition/amendment when uncertain
            if any(x in ntype for x in ('award','result','completion','contract modification','planning')) and not any(x in ntype for x in ('competition','contract notice')):continue
            deadline=pdt(first(o,'deadline','submissiondeadline','receipttender','enddate'))
            pub=pdt(first(o,'publicationdate','publisheddate','dispatchdate')) or datetime.combine(d,datetime.min.time(),tzinfo=timezone.utc)
            buyer=first(o,'buyername','organisationname','organizationname','contractingauthority')
            value=first(o,'estimatedvalue','estimatedoverallcontractamount','valueamount')
            currency=first(o,'currency','currencyid')
            docs=[clean(x) for x in walk_values(o,('url','uri','href')) if str(x).startswith('http') and re.search(r'\.(pdf|zip|docx?|xlsx?|xls|pptx?)(?:\?|$)',str(x),re.I)]
            rid=nid or str(abs(hash((title,buyer,pub.isoformat()))))
            rows.append({'candidate_id':f'LV-IUB:{rid}','source':'LV_IUB','portal':'LV_IUB','notice_id':nid,'title':title or rid,'buyer':buyer,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat(),'current':not deadline or deadline>=NOW,'notice_url':None,'estimated_value':value,'currency':currency or 'EUR','description':first(o,'description','shortdescription') or '', 'route':{'document_urls':list(dict.fromkeys(docs))},'raw_notice_type':ntype or None,'source_file':url,'discovered_at':NOW.isoformat()})
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'LV_IUB','raw_materialized':len(rows),'current_materialized':len(cur),'lookback_days':DAYS,'generated_at':NOW.isoformat(),'errors':[],'official_url':BASE,'telemetry':tele,'archive_available_from':'2013-01-01'}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
