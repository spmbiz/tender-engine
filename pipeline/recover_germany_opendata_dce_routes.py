#!/usr/bin/env python3
from __future__ import annotations

"""Recover archived German procurement-document routes from official OpenData eForms exports.

The Publication Service OpenData API exposes retrospective daily/monthly notice
exports. This tool matches canonical Official_Notice_ID values inside daily
exports, extracts URL candidates from the authoritative notice payload, and
builds resolver-ready historical candidates. It never authenticates or bypasses
participation gates and never creates a final live verdict.
"""

import argparse, io, json, re, zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

URL_RE = re.compile(rb"https?://[^\s<>\"']+", re.I)
BAD_HOSTS = {
    'oeffentlichevergabe.de','www.oeffentlichevergabe.de','ted.europa.eu','eur-lex.europa.eu',
    'simap.ted.europa.eu','www.w3.org','docs.oasis-open.org','joinup.ec.europa.eu',
}


def norm_url(raw: str) -> str:
    u=(raw or '').strip().rstrip('.,;:)]}>')
    return u.replace('&amp;','&')


def score_url(url: str, context: str='') -> int:
    try: host=(urlparse(url).hostname or '').casefold()
    except Exception: host=''
    s=0; hay=(url+' '+context).casefold()
    if host and host not in BAD_HOSTS: s+=4
    if any(x in hay for x in ('vergabeunterlag','ausschreibungsunterlag','procurement-document','procurement_document','tender-document','tender_document')): s+=10
    if any(x in hay for x in ('download','document','unterlag','bieterportal','vergabeportal','evergabe','e-vergabe')): s+=5
    if re.search(r'\.(pdf|zip|7z|docx?|xlsx?)(?:$|[?#])',url,re.I): s+=8
    if any(x in hay for x in ('callfortenders','documentreference','accessurl','uri','url')): s+=2
    if host in BAD_HOSTS: s-=7
    if url.casefold().startswith('https://oeffentlichevergabe.de/ui/'): s-=10
    return s


def iter_zip_members(blob: bytes, prefix=''):
    if not blob.startswith(b'PK\x03\x04'): return
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                if name.endswith('/'): continue
                try: data=z.read(name)
                except Exception: continue
                full=prefix+name
                if data.startswith(b'PK\x03\x04'):
                    yield from iter_zip_members(data,full+'!')
                else:
                    yield full,data
    except Exception:
        return


def extract_urls(name: str, data: bytes) -> list[dict]:
    out={}
    text=data.decode('utf-8',errors='replace')
    for m in re.finditer(r'https?://[^\s<>\"\']+',text,re.I):
        u=norm_url(m.group(0)); ctx=text[max(0,m.start()-220):m.end()+220]
        if u: out[u]=max(out.get(u,-999),score_url(u,ctx))
    try:
        root=ET.fromstring(data)
        for elem in root.iter():
            val=(elem.text or '').strip()
            if val.startswith(('http://','https://')):
                tag=elem.tag.split('}')[-1]
                u=norm_url(val); out[u]=max(out.get(u,-999),score_url(u,tag))
            for k,v in elem.attrib.items():
                if str(v).startswith(('http://','https://')):
                    u=norm_url(str(v)); out[u]=max(out.get(u,-999),score_url(u,k+' '+elem.tag.split('}')[-1]))
    except Exception:
        pass
    return [{'url':u,'score':s,'member':name} for u,s in sorted(out.items(),key=lambda x:(-x[1],x[0]))]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--queue-summary',required=True); ap.add_argument('--out',required=True); ap.add_argument('--timeout',type=int,default=90); a=ap.parse_args()
    source=json.loads(Path(a.queue_summary).read_text(encoding='utf-8'))
    candidates=source.get('candidates') or []
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); (out/'matched').mkdir(exist_ok=True)
    by_day={}
    for c in candidates: by_day.setdefault(str(c.get('publication_date') or '')[:10],[]).append(c)
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/GermanyOpenDataRecovery-1.0 public procurement research'})
    export_meta={}; results=[]
    for day,cs in sorted(by_day.items()):
        url='https://oeffentlichevergabe.de/api/notice-exports?pubDay='+day
        try:
            r=session.get(url,timeout=a.timeout); blob=r.content
            export_meta[day]={'http_status':r.status_code,'bytes':len(blob),'content_type':r.headers.get('content-type'),'content_disposition':r.headers.get('content-disposition'),'zip_magic':blob.startswith(b'PK\x03\x04')}
        except Exception as exc:
            export_meta[day]={'error':repr(exc)}
            for c in cs: results.append({'candidate':c,'matched':False,'error':repr(exc),'urls':[]})
            continue
        members=list(iter_zip_members(blob)) if blob.startswith(b'PK\x03\x04') else [('export.bin',blob)]
        for c in cs:
            nid=str(c.get('official_notice_id') or '').strip(); nidb=nid.casefold().encode()
            matches=[]
            for name,data in members:
                if nidb in data.lower(): matches.append((name,data))
            urls=[]
            for name,data in matches:
                safe=re.sub(r'[^A-Za-z0-9._-]+','_',str(c.get('candidate_id') or 'candidate'))[:90]
                ext=Path(name.split('!')[-1]).suffix or '.bin'
                target=out/'matched'/f'{safe}__{len(urls)}{ext}'
                if not target.exists(): target.write_bytes(data)
                urls.extend(extract_urls(name,data))
            best={}
            for x in urls:
                u=x['url']; prev=best.get(u)
                if prev is None or x['score']>prev['score']: best[u]=x
            ranked=sorted(best.values(),key=lambda x:(-x['score'],x['url']))
            results.append({'candidate':c,'matched':bool(matches),'matched_members':[n for n,_ in matches],'urls':ranked[:60]})
    resolver=[]
    for res in results:
        c=dict(res['candidate']); ranked=[x for x in res['urls'] if x['score']>0]
        route=dict(c.get('route') or {})
        route['document_urls']=[x['url'] for x in ranked[:20]]
        c['route']=route;c['opendata_eforms_match']=res['matched'];c['opendata_url_candidates']=ranked[:20];c['final_verdict_allowed']=False
        resolver.append(c)
    with (out/'resolver_queue.jsonl').open('w',encoding='utf-8') as f:
        for c in resolver:f.write(json.dumps(c,ensure_ascii=False,separators=(',',':'))+'\n')
    (out/'recovery_results.json').write_text(json.dumps({'exports':export_meta,'results':results},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    summary={'contract':'GERMANY_OPENDATA_DCE_ROUTE_RECOVERY_V1','candidates':len(candidates),'matched_notices':sum(r['matched'] for r in results),'candidates_with_positive_urls':sum(any(x['score']>0 for x in r['urls']) for r in results),'daily_exports':len(by_day),'export_bytes':sum(int(x.get('bytes') or 0) for x in export_meta.values()),'top_hosts':dict(Counter((urlparse(x['url']).hostname or '') for r in results for x in r['urls'] if x['score']>0)),'final_verdict_allowed':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
