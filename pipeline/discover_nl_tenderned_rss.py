from __future__ import annotations

import json, os, re, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/NL_TENDERNED_RSS')); OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
URL='https://www.tenderned.nl/papi/tenderned-rs-tns/rss/laatste-publicatie.rss'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.5 (+public procurement research)','Accept':'application/rss+xml,application/xml,text/xml,*/*'})
def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        from email.utils import parsedate_to_datetime
        x=parsedate_to_datetime(s)
        if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:pass
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return (x if x.tzinfo else x.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:return None

def field(desc,label):
    m=re.search(rf'(?:^|\|)\s*{re.escape(label)}\s*:\s*([^|]+)',desc or '',re.I)
    return clean(m.group(1)) if m else None

def deadline_from_desc(desc):
    raw=field(desc,'Sluitingsdatum')
    if not raw:return None
    for fmt in ('%d-%m-%Y %H:%M','%d-%m-%Y','%d/%m/%Y %H:%M','%d/%m/%Y'):
        try:
            x=datetime.strptime(raw,fmt).replace(tzinfo=ZoneInfo('Europe/Amsterdam'))
            if fmt in ('%d-%m-%Y','%d/%m/%Y'):x=x.replace(hour=23,minute=59,second=59)
            return x.astimezone(timezone.utc)
        except Exception:pass
    return None

def main():
    r=S.get(URL,timeout=90);r.raise_for_status();root=ET.fromstring(r.content)
    items=root.findall('.//item')
    if not items: items=[x for x in root.iter() if x.tag.rsplit('}',1)[-1]=='entry']
    rows=[]
    for it in items:
        vals={}
        for c in it.iter():vals[c.tag.rsplit('}',1)[-1].lower()]=clean(c.text)
        title=vals.get('title');link=vals.get('link') or vals.get('id') or vals.get('guid')
        if not link:
            for c in it.iter():
                h=c.attrib.get('href')
                if h:link=h;break
        guid=vals.get('guid') or vals.get('id') or link or title
        pub=pdt(vals.get('pubdate') or vals.get('published') or vals.get('updated'))
        desc=vals.get('description') or vals.get('summary') or ''
        deadline=deadline_from_desc(desc)
        pubtype=field(desc,'Type publicatie'); assignment=field(desc,'Type opdracht'); procedure=field(desc,'Procedure'); cpv=field(desc,'CPV')
        # TenderNed RSS also emits award/result/amendment publications. Retain raw but only expose open/unknown calls as current.
        expired=bool(deadline and deadline<NOW)
        resultish=bool(re.search(r'gegund|gunning|resultaat|award|voltooide|intrekking',f'{pubtype} {title}',re.I))
        current=not expired and not resultish
        cid='NL-TN:'+re.sub(r'[^A-Za-z0-9._:-]+','_',clean(guid))[-180:]
        rows.append({'candidate_id':cid,'source':'NL_TENDERNED_RSS','portal':'NL_TENDERNED','notice_id':clean(guid),'title':title or desc[:240],'buyer':None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':current,'notice_url':urljoin('https://www.tenderned.nl/',link) if link else None,'description':desc,'publication_type':pubtype,'assignment_type':assignment,'procedure':procedure,'cpv':cpv,'route':{'document_urls':[],'detail_url':urljoin('https://www.tenderned.nl/',link) if link else None},'discovered_at':NOW.isoformat()})
    seen={};
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'NL_TENDERNED_RSS','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'generated_at':NOW.isoformat(),'errors':[],'official_url':URL,'download_bytes':len(r.content)}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
