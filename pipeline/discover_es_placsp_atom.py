from __future__ import annotations

import json, os, re, time, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests

import placsp_atom

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/ES_PLACSP')); OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
LOOKBACK=max(1,int(os.getenv('LOOKBACK_DAYS','3')))
MAX_PAGES=max(1,min(12,int(os.getenv('ES_MAX_PAGES','4'))))
REQUEST_TIMEOUT=max(10,min(90,int(os.getenv('ES_REQUEST_TIMEOUT','40'))))
PARSE_RETRIES=max(1,min(6,int(os.getenv('ES_PARSE_RETRIES','3'))))
CUTOFF=NOW-timedelta(days=LOOKBACK)
FEEDS=[
 ('hosted',placsp_atom.HOSTED_FEED),
 ('aggregated',placsp_atom.AGGREGATED_FEED),
]
S=requests.Session(); S.headers.update({'User-Agent':'Tender-Engine/4.5 (+public procurement research)','Accept':'application/atom+xml,application/xml,text/xml,*/*'})

def clean(v): return ' '.join(str(v or '').split())
def local(tag): return tag.rsplit('}',1)[-1] if '}' in tag else tag
def pdt(v):
    if not v:return None
    s=clean(v)
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'))
        if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:return None

def texts(root,name): return [clean(x.text) for x in root.iter() if local(x.tag)==name and clean(x.text)]
def first(root,*names):
    for n in names:
        xs=texts(root,n)
        if xs:return xs[0]
    return None

def atom_child(entry,name):
    for x in list(entry):
        if local(x.tag)==name:return clean(x.text)
    return None

def find_links(entry):
    out=[]
    for x in entry.iter():
        if local(x.tag) in ('URI','URL') and clean(x.text):out.append(clean(x.text))
        href=x.attrib.get('href')
        if href:out.append(href)
    return list(dict.fromkeys(out))

def deadline_from(entry):
    vals=[]
    for n in ('EndDate','EndDateTime','TenderSubmissionDeadlinePeriod','DeadlineDate','ReceiptDeadlineDate','SubmissionDueDate'):
        vals.extend(texts(entry,n))
    for v in vals:
        x=pdt(v)
        if x:return x
    dates=texts(entry,'EndDate')+texts(entry,'DeadlineDate')
    times=texts(entry,'EndTime')+texts(entry,'DeadlineTime')
    if dates:return pdt(dates[0] + ('T'+times[0] if times else ''))
    return None

def fetch_xml(url,page,telemetry):
    last=None
    for attempt in range(1,PARSE_RETRIES+1):
        try:
            r=S.get(url,timeout=REQUEST_TIMEOUT,headers={'Cache-Control':'no-cache' if attempt>1 else 'max-age=0'})
            item={'page':page,'url':url,'status':r.status_code,'bytes':len(r.content),'attempt':attempt,'content_type':r.headers.get('content-type')}
            r.raise_for_status()
            try:
                root=ET.fromstring(r.content)
                item['parse_ok']=True
                telemetry.append(item)
                return root
            except ET.ParseError as exc:
                item['parse_ok']=False; item['parse_error']=repr(exc)
                try:item['parse_position']={'line':exc.position[0],'column':exc.position[1]}
                except Exception:pass
                telemetry.append(item); last=exc
        except Exception as exc:
            telemetry.append({'page':page,'url':url,'attempt':attempt,'error':repr(exc)})
            last=exc
        if attempt<PARSE_RETRIES:time.sleep(min(6,attempt*1.5))
    raise RuntimeError(f'PLACSP feed remained unreadable after {PARSE_RETRIES} attempts: {last!r}')

def parse_feed(kind,start):
    url=start; page=0; records=[]; telemetry=[]; seen=set()
    while url and page<MAX_PAGES and url not in seen:
        seen.add(url); page+=1
        root=fetch_xml(url,page,telemetry)
        entries=[x for x in root if local(x.tag)=='entry']
        oldest=None
        for e in entries:
            updated=pdt(atom_child(e,'updated') or atom_child(e,'published'))
            if updated and (oldest is None or updated<oldest):oldest=updated
            atom_id=atom_child(e,'id'); atom_title=atom_child(e,'title')
            folder=first(e,'ContractFolderID','ContractFolderStatusCode','ID')
            project_title=first(e,'Name','Title') or atom_title
            desc=first(e,'Description') or ''
            buyer=first(e,'PartyName','CorporateRegistrationSchemeName')
            amount=first(e,'EstimatedOverallContractAmount','TotalAmount','TaxExclusiveAmount')
            currency=None
            for x in e.iter():
                if local(x.tag) in ('EstimatedOverallContractAmount','TotalAmount','TaxExclusiveAmount') and clean(x.text):
                    currency=x.attrib.get('currencyID') or x.attrib.get('currency'); break
            deadline=deadline_from(e)
            links=find_links(e)
            detail=next((u for u in links if 'contrataciondelestado' in u and ('detalle' in u.lower() or 'poc' in u.lower())),links[0] if links else None)
            rid=clean(atom_id or folder)
            if not rid and not project_title:continue
            cid=placsp_atom.candidate_id(e) if rid else 'ES-PLACSP:'+str(abs(hash((project_title,buyer,str(updated)))))
            document_urls=placsp_atom.document_urls(e,start)
            records.append({
                'candidate_id':cid,
                'source':'ES_PLACSP',
                'portal':'ES_PLACSP',
                'notice_id':clean(folder or atom_id),
                'title':clean(project_title),
                'buyer':clean(buyer) or None,
                'country':'ES',
                'deadline':deadline.isoformat() if deadline else None,
                'published':updated.isoformat() if updated else None,
                'current':not deadline or deadline>=NOW,
                'notice_url':detail,
                'estimated_value':amount,
                'currency':currency,
                'description':clean(desc),
                'route':{
                    'document_urls':document_urls,
                    'atom_id':clean(atom_id) or None,
                    'contract_folder_id':clean(folder) or None,
                    'atom_feed_url':start,
                    'feed_lane':kind,
                },
                'feed_lane':kind,
                'discovered_at':NOW.isoformat(),
            })
        nxt=None
        for x in root.iter():
            if local(x.tag)=='link' and x.attrib.get('rel')=='next':nxt=x.attrib.get('href');break
        if oldest and oldest<CUTOFF: break
        url=urljoin(url,nxt) if nxt else None
    return records,telemetry

def main():
    allr={}; tele={}
    for kind,url in FEEDS:
        try:r,t=parse_feed(kind,url);tele[kind]=t
        except Exception as exc:tele[kind]=[{'error':repr(exc),'url':url}];continue
        for x in r:
            old=allr.get(x['candidate_id'])
            if not old or str(x.get('published') or '')>=str(old.get('published') or ''):allr[x['candidate_id']]=x
    rows=list(allr.values()); current=[x for x in rows if x.get('current',True)]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',current)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    errors=[]
    if not rows:errors.append({'type':'NO_ROWS','telemetry':tele})
    stats={
        'source':'ES_PLACSP',
        'raw_materialized':len(rows),
        'current_materialized':len(current),
        'with_direct_document_urls':sum(1 for x in rows if (x.get('route') or {}).get('document_urls')),
        'direct_document_url_count':sum(len((x.get('route') or {}).get('document_urls') or []) for x in rows),
        'lookback_days':LOOKBACK,
        'max_pages_per_feed':MAX_PAGES,
        'parse_retries':PARSE_RETRIES,
        'generated_at':NOW.isoformat(),
        'errors':errors,
        'official_feeds':[x[1] for x in FEEDS],
        'telemetry':tele,
    }
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows: raise SystemExit(3)

if __name__=='__main__':main()
