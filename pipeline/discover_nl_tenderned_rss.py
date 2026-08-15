from __future__ import annotations

import json, os, re, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/NL_TENDERNED_RSS')); OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
URL='https://www.tenderned.nl/papi/tenderned-rs-tns/rss/laatste-publicatie.rss'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.4 (+public procurement research)','Accept':'application/rss+xml,application/xml,text/xml,*/*'})
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
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None

def tx(node,name):
    x=node.find(name)
    return clean(x.text) if x is not None and x.text else None

def main():
    r=S.get(URL,timeout=90);r.raise_for_status();root=ET.fromstring(r.content)
    items=root.findall('.//item')
    if not items: items=[x for x in root.iter() if x.tag.rsplit('}',1)[-1]=='entry']
    rows=[]
    for it in items:
        vals={}
        for c in it.iter():
            vals[c.tag.rsplit('}',1)[-1].lower()]=clean(c.text)
        title=vals.get('title');link=vals.get('link') or vals.get('id') or vals.get('guid')
        if not link:
            for c in it.iter():
                h=c.attrib.get('href')
                if h:link=h;break
        guid=vals.get('guid') or vals.get('id') or link or title
        pub=pdt(vals.get('pubdate') or vals.get('published') or vals.get('updated'))
        desc=vals.get('description') or vals.get('summary') or ''
        # RSS is a publication stream, not a canonical close-date feed. Keep recent entries current and let downstream page/DCE resolve deadline.
        cid='NL-TN:'+re.sub(r'[^A-Za-z0-9._:-]+','_',clean(guid))[-180:]
        rows.append({'candidate_id':cid,'source':'NL_TENDERNED_RSS','portal':'NL_TENDERNED','notice_id':clean(guid),'title':title or desc[:240],'buyer':None,'deadline':None,'published':pub.isoformat() if pub else None,'current':True,'notice_url':urljoin('https://www.tenderned.nl/',link) if link else None,'description':desc,'route':{'document_urls':[]},'discovered_at':NOW.isoformat()})
    seen={};
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values())
    for fn in ('raw.jsonl','current.jsonl'):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in rows:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'NL_TENDERNED_RSS','raw_materialized':len(rows),'current_materialized':len(rows),'generated_at':NOW.isoformat(),'errors':[],'official_url':URL,'download_bytes':len(r.content)}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
