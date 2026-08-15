#!/usr/bin/env python3
from __future__ import annotations

"""Cheap historical DCE access probe.

Reads a historical research queue and checks only public HTTP access state. It
never authenticates, never bypasses CAPTCHA/interest gates, and never creates a
bid verdict. Positive rows can later be sent to the full DCE resolver.
"""

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

FILE_RE = re.compile(r"(?:\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|7z)(?:$|[?#])|download|document|dokument|unterlagen|vergabeunterlag|attachment|pi[eè]ce|telecharg|dce)", re.I)
AUTH_RE = re.compile(r"\blog[ -]?in\b|sign in|se connecter|connexion|anmelden|registrieren|identification|compte utilisateur", re.I)
CAPTCHA_RE = re.compile(r"captcha|recaptcha|security code|code de s[eé]curit[eé]|verification code", re.I)
INTEREST_RE = re.compile(r"express interest|register interest|record(?:ing)? your interest|manifester.*int[eé]r[eê]t|association.*entreprise", re.I)


def load_jsonl(path: Path) -> list[dict]:
    out=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line: continue
        obj=json.loads(line)
        if isinstance(obj,dict): out.append(obj)
    return out


def fetch_one(rec: dict, timeout: int, max_bytes: int) -> dict:
    url=str(rec.get('notice_url') or rec.get('primary_source_url') or '').strip()
    base={
        'candidate_id':rec.get('candidate_id'),'historical_sub_niche':rec.get('historical_sub_niche'),
        'portal':rec.get('portal'),'source':rec.get('source'),'country':rec.get('country'),
        'buyer':rec.get('buyer'),'title':rec.get('title'),'notice_url':url,
        'final_verdict_allowed':False,
    }
    if not url.startswith(('http://','https://')):
        return {**base,'access_state':'NO_URL','http_status':None,'resolved_url':None,'content_type':None,'bytes_read':0,'document_candidates':[]}
    s=requests.Session(); s.headers.update({'User-Agent':'Tender-Engine/HistDCEProbe-1.0 public procurement research','Accept':'text/html,application/xhtml+xml,application/pdf,application/zip,application/octet-stream,*/*'})
    try:
        with s.get(url,timeout=timeout,allow_redirects=True,stream=True) as r:
            chunks=[]; total=0
            for chunk in r.iter_content(65536):
                if not chunk: continue
                take=chunk[:max(0,max_bytes-total)]
                chunks.append(take); total+=len(take)
                if total>=max_bytes: break
            body=b''.join(chunks); ct=(r.headers.get('content-type') or '').lower(); cd=(r.headers.get('content-disposition') or '').lower(); magic=body[:8]
            direct_file=bool(r.ok and body and ('attachment' in cd or any(x in ct for x in ('application/pdf','application/zip','application/octet-stream','application/vnd')) or magic.startswith(b'%PDF-') or magic.startswith(b'PK\x03\x04')))
            text=''
            docs=[]
            if not direct_file and ('html' in ct or 'text/' in ct or body.lstrip().startswith(b'<')):
                text=body.decode(r.encoding or 'utf-8',errors='replace')
                for href in re.findall(r'href\s*=\s*[\"\']([^\"\']+)[\"\']',text,re.I):
                    absolute=urljoin(r.url,html.unescape(href))
                    if absolute.startswith(('http://','https://')) and FILE_RE.search(absolute): docs.append(absolute)
                docs=list(dict.fromkeys(docs))[:40]
            visible=re.sub(r'<script\b[^>]*>.*?</script>',' ',text,flags=re.I|re.S)
            visible=re.sub(r'<style\b[^>]*>.*?</style>',' ',visible,flags=re.I|re.S)
            visible=re.sub(r'<[^>]+>',' ',visible)
            visible=re.sub(r'\s+',' ',html.unescape(visible))[:250000]
            if direct_file: state='DIRECT_FILE'
            elif docs: state='DOCUMENT_LINKS_FOUND'
            elif r.status_code in (401,403) or AUTH_RE.search(visible): state='AUTH_REQUIRED'
            elif CAPTCHA_RE.search(visible): state='CAPTCHA_REQUIRED'
            elif INTEREST_RE.search(visible): state='INTEREST_REQUIRED'
            elif r.ok: state='PAGE_ALIVE_NO_DOC_LINK'
            elif r.status_code==404: state='NOT_FOUND'
            elif r.status_code==429 or r.status_code>=500: state='RETRYABLE_HTTP'
            else: state='HTTP_ERROR'
            return {**base,'access_state':state,'http_status':r.status_code,'resolved_url':r.url,'content_type':r.headers.get('content-type'),'bytes_read':len(body),'document_candidates':docs}
    except requests.Timeout:
        return {**base,'access_state':'TIMEOUT','http_status':None,'resolved_url':None,'content_type':None,'bytes_read':0,'document_candidates':[]}
    except Exception as exc:
        return {**base,'access_state':'ERROR','http_status':None,'resolved_url':None,'content_type':None,'bytes_read':0,'document_candidates':[],'error':repr(exc)[:500]}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--queue',required=True); ap.add_argument('--out',required=True); ap.add_argument('--workers',type=int,default=12); ap.add_argument('--timeout',type=int,default=18); ap.add_argument('--max-bytes',type=int,default=2_000_000); a=ap.parse_args()
    q=load_jsonl(Path(a.queue)); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,a.workers)) as ex:
        futs={ex.submit(fetch_one,r,a.timeout,a.max_bytes):r for r in q}
        for fut in as_completed(futs): results.append(fut.result())
    results.sort(key=lambda r:(str(r.get('historical_sub_niche')),str(r.get('candidate_id'))))
    with (out/'access_probe.jsonl').open('w',encoding='utf-8') as f:
        for r in results: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    actionable=[]
    positive={'DIRECT_FILE','DOCUMENT_LINKS_FOUND','PAGE_ALIVE_NO_DOC_LINK','INTEREST_REQUIRED','AUTH_REQUIRED','CAPTCHA_REQUIRED'}
    for r in results:
        if r['access_state'] not in positive: continue
        src=next((x for x in q if x.get('candidate_id')==r.get('candidate_id')),None)
        if not src: continue
        x=dict(src); route=dict(x.get('route') or {})
        if r.get('resolved_url'): route['detail_url']=r['resolved_url']; x['notice_url']=r['resolved_url']
        if r.get('document_candidates'): route['document_urls']=r['document_candidates']
        x['route']=route; x['historical_access_probe']=r['access_state']; actionable.append(x)
    with (out/'resolver_candidates.jsonl').open('w',encoding='utf-8') as f:
        for r in actionable: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    by_niche=defaultdict(Counter); by_portal=defaultdict(Counter)
    for r in results:
        by_niche[r['historical_sub_niche']][r['access_state']]+=1; by_portal[r['portal']][r['access_state']]+=1
    states=Counter(r['access_state'] for r in results)
    summary={
      'contract':'HISTORICAL_DCE_ACCESS_PROBE_V1','total':len(results),'states':dict(states),
      'resolver_candidates':len(actionable),'by_subniche':{k:dict(v) for k,v in sorted(by_niche.items())},
      'by_portal':{k:dict(v) for k,v in sorted(by_portal.items())},'final_verdict_allowed':False,
      'note':'HTTP/public-access research only; authentication/CAPTCHA/interest gates are surfaced, never bypassed.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
