from __future__ import annotations

import json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/AT_DATAGV'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);LOOKBACK=max(7,min(120,int(os.getenv('LOOKBACK_DAYS','30'))));ROWS=max(50,min(1000,int(os.getenv('AT_ROWS','300'))));FEEDS=max(10,min(300,int(os.getenv('AT_FEEDS','80'))))
API_ENDPOINTS=['https://www.data.gv.at/katalog/api/3/action/package_search','https://www.data.gv.at/api/3/action/package_search']
SEARCH='https://www.data.gv.at/suche/?searchterm=&tagFilter_sub%5B%5D=Ausschreibung'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.4 (+public procurement research)','Accept':'application/json,application/xml,text/xml,*/*'})

def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:pass
    for fmt in ('%Y-%m-%d','%d.%m.%Y','%Y-%m-%d %H:%M:%S'):
        try:return datetime.strptime(s[:19],fmt).replace(tzinfo=timezone.utc)
        except Exception:pass
    return None

def api_search():
    tele=[];packages=[]
    variants=[{'q':'Ausschreibung','rows':ROWS},{'fq':'tags:Ausschreibung','rows':ROWS},{'q':'tags:Ausschreibung','rows':ROWS}]
    for base in API_ENDPOINTS:
        for params in variants:
            try:r=S.get(base,params=params,timeout=60);tele.append({'url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')})
            except Exception as exc:tele.append({'base':base,'params':params,'error':repr(exc)});continue
            if not r.ok:continue
            try:d=r.json()
            except Exception:continue
            result=d.get('result') if isinstance(d,dict) else None
            arr=result.get('results') if isinstance(result,dict) else None
            if isinstance(arr,list) and arr:
                packages=arr;return packages,tele,base,params
    return packages,tele,None,None

def text_nodes(root):
    out={}
    for el in root.iter():
        tag=el.tag.split('}')[-1].lower();txt=clean(el.text)
        if txt:out.setdefault(tag,[]).append(txt)
    return out

def first(n,*keys):
    for k in keys:
        vals=n.get(k.lower())
        if vals:return vals[0]
    return None

def parse_feed(url):
    try:r=S.get(url,timeout=60,allow_redirects=True)
    except Exception as exc:return [],{'url':url,'error':repr(exc)}
    meta={'url':url,'resolved_url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')}
    if not r.ok or not r.content:return [],meta
    try:root=ET.fromstring(r.content)
    except Exception as exc:meta['parse_error']=repr(exc);return [],meta
    records=[]
    # A Kerndatenquelle may be a feed/wrapper; find descendants that contain a title plus an identifier/date.
    candidates=list(root)
    if len(candidates)<=1:candidates=[root]
    for el in candidates:
        nodes=text_nodes(el)
        title=clean(first(nodes,'title','bezeichnung','name','auftragsgegenstand','description'))
        nid=clean(first(nodes,'id','identifier','uuid','verfahrensid','bekanntmachungsid'))
        pub=pdt(first(nodes,'issued','modified','date','publicationdate','veroeffentlichungsdatum'))
        deadline=pdt(first(nodes,'deadline','submissiondeadline','angebotsfrist','teilnahmefrist','enddate'))
        buyer=clean(first(nodes,'publisher','auftraggeber','organization','organisation','buyer'))
        if not (title or nid):continue
        urls=[]
        for x in el.iter():
            for av in x.attrib.values():
                if isinstance(av,str) and av.startswith('http') and av not in urls:urls.append(av)
            t=clean(x.text)
            if t.startswith('http') and t not in urls:urls.append(t)
        rid=nid or str(abs(hash((title,buyer,str(pub),url))))
        current=bool((deadline and deadline>=NOW) or (not deadline and pub and pub>=NOW-timedelta(days=LOOKBACK)))
        records.append({'candidate_id':f'AT-DATAGV:{rid}','source':'AT_DATAGV','portal':'AT_NATIONAL','notice_id':nid or None,'title':title or rid,'buyer':buyer or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':current,'notice_url':next((u for u in urls if 'data.gv.at' not in u),url),'description':'','route':{'document_urls':[u for u in urls if re.search(r'\.(pdf|zip|docx?|xlsx?)(?:[?#]|$)',u,re.I)],'public_urls':urls[:30],'source_feed':url},'discovered_at':NOW.isoformat()})
    return records,meta

def main():
    packages,tele,base,params=api_search();resources=[]
    for p in packages:
        tags=' '.join(str((t or {}).get('name') or '') for t in p.get('tags') or []);title=clean(p.get('title') or p.get('name'))
        if 'ausschreibung' not in (tags+' '+title).lower():continue
        for r in p.get('resources') or []:
            if not isinstance(r,dict):continue
            url=r.get('url');fmt=clean(r.get('format') or r.get('mimetype'));name=clean(r.get('name') or r.get('description'))
            if isinstance(url,str) and ('xml' in (fmt+' '+name+url).lower() or 'kerndaten' in (name+url).lower()):resources.append({'url':url,'name':name,'format':fmt,'package':p.get('id') or p.get('name')})
    # deterministic URL dedupe
    uniq=[];seen=set()
    for x in resources:
        if x['url'] not in seen:seen.add(x['url']);uniq.append(x)
    rows=[];feed_tele=[]
    for x in uniq[:FEEDS]:
        recs,m=parse_feed(x['url']);feed_tele.append(m);rows.extend(recs)
    seenr={}
    for x in rows:seenr[x['candidate_id']]=x
    rows=list(seenr.values());cur=[x for x in rows if x['current']]
    for fn,arr in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in arr:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    errors=[]
    if not packages:errors.append({'type':'OFFICIAL_CATALOG_API_UNRESOLVED'})
    elif not uniq:errors.append({'type':'NO_AUSSCHREIBUNG_XML_RESOURCES'})
    elif not rows:errors.append({'type':'XML_RESOURCES_PARSED_NO_RECORDS'})
    stats={'source':'AT_DATAGV','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'published_parsed':sum(bool(x['published']) for x in rows),'packages_found':len(packages),'xml_resources_found':len(uniq),'feeds_attempted':min(len(uniq),FEEDS),'generated_at':NOW.isoformat(),'errors':errors,'official_search':SEARCH,'api_endpoint':base,'api_query':params,'telemetry':tele,'feed_telemetry':feed_tele[:100]}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False));print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
