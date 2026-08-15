from __future__ import annotations

import json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/FI_HILMA'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);LOOKBACK=max(7,min(90,int(os.getenv('LOOKBACK_DAYS','30'))));TOP=max(25,min(100,int(os.getenv('FI_TOP','75'))));MAX_PAGES=max(1,min(12,int(os.getenv('FI_MAX_PAGES','5'))))
BASE='https://www.hankintailmoitukset.fi';SEARCH=BASE+'/en/search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.2 (+public procurement research)','Accept':'text/html,application/xhtml+xml'})
LINK_RE=re.compile(r'^/(?:en|fi|sv)/public/(?:procedure|procurement)/\d+/(?:enotice|notice)/\d+(?:/.*)?$',re.I)
DOC_HINT=re.compile(r'(procurement documents|documents url|asiakirjat|tarjouspalvelu|cloudia|mercell|tendsign|hanki|tarjous|\.pdf|\.zip|\.docx?)',re.I)

def clean(v):return ' '.join(str(v or '').split())
def dtparse(s):
    s=clean(s)
    if not s:return None
    for pat in (r'(20\d{2})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})',r'(\d{1,2})\.(\d{1,2})\.(20\d{2})\s+(\d{1,2}):(\d{2})',r'(\d{1,2})\.(\d{1,2})\.(20\d{2})'):
        m=re.search(pat,s)
        if not m:continue
        try:
            if pat.startswith('(20'): y,mo,d,h,mi=map(int,m.groups())
            elif len(m.groups())==5:d,mo,y,h,mi=map(int,m.groups())
            else:d,mo,y=map(int,m.groups());h=mi=0
            return datetime(y,mo,d,h,mi,tzinfo=timezone.utc)
        except Exception:pass
    return None

def label_after(text,*labels):
    for label in labels:
        m=re.search(re.escape(label)+r'\s+([^\n]{1,500})',text,re.I)
        if m:return clean(m.group(1))
    return None

def fetch_detail(url):
    try:r=S.get(url,timeout=45);r.raise_for_status()
    except Exception as exc:return {'url':url,'error':repr(exc)}
    soup=BeautifulSoup(r.text,'html.parser');text='\n'.join(clean(x) for x in soup.stripped_strings)
    h1=soup.find('h1');title=clean(h1.get_text(' ',strip=True) if h1 else '')
    if not title:
        title=label_after(text,'Title TED BT-21: Title','Title of the procurement','Ilmoituksen nimi TED BT-21: Nimi') or clean(soup.title.string if soup.title and soup.title.string else '')
    buyer=label_after(text,'Organisation Name TED BT-500: Organisation Name','Organisaation virallinen nimi TED BT-500: Organisaation nimi','Organisation Name')
    pubtxt=label_after(text,'Published in Hilma','Julkaistu Hilmassa','Publicerad i Hilma')
    published=dtparse(pubtxt or '')
    deadline=None
    for label in ('Time limit for receipt of tenders','Time limit for submission','Tenders or requests to participate due','Tarjousten tai osallistumishakemusten vastaanottamisen määräaika','Määräaika'):
        p=text.lower().find(label.lower())
        if p>=0:
            deadline=dtparse(text[p:p+350]);
            if deadline:break
    notice_id=label_after(text,'Notice Hilma-number','Ilmoituksen Hilma-numero','HILMA number')
    ted=label_after(text,'TED number','Ilmoituksen TED-numero')
    procedure_id=label_after(text,'Procurement procedure identifier','Hankintamenettelyn tunniste')
    cpv=[]
    for m in re.finditer(r'\b(\d{8})\b',text):
        if m.group(1) not in cpv:cpv.append(m.group(1))
        if len(cpv)>=20:break
    hrefs=[]
    for a in soup.find_all('a',href=True):
        href=urljoin(r.url,a.get('href'));label=clean(a.get_text(' ',strip=True))
        if href.startswith('http') and (DOC_HINT.search(href) or DOC_HINT.search(label)):hrefs.append(href)
    # Prefer URLs after the procurement-documents label when the page renders it as plain text.
    for m in re.findall(r'https?://[^\s<>"\']+',text):
        u=m.rstrip(').,;')
        if DOC_HINT.search(u):hrefs.append(u)
    hrefs=list(dict.fromkeys(hrefs))[:40]
    direct=[u for u in hrefs if re.search(r'\.(pdf|zip|7z|docx?|xlsx?|pptx?)(?:[?#]|$)',u,re.I)]
    proceeding=next((u for u in hrefs if u not in direct and BASE not in u),None)
    if not proceeding:proceeding=r.url
    current=bool((deadline and deadline>=NOW) or (not deadline and (not published or published>=NOW-timedelta(days=LOOKBACK))))
    return {'candidate_id':f"FI-HILMA:{notice_id or procedure_id or abs(hash(r.url))}",'source':'FI_HILMA','portal':'FI_HILMA','notice_id':notice_id,'ted_number':ted,'procedure_id':procedure_id,'title':title,'buyer':buyer,'deadline':deadline.isoformat() if deadline else None,'published':published.isoformat() if published else None,'current':current,'notice_url':r.url,'cpv':cpv,'description':'','route':{'document_urls':direct,'proceeding_url':proceeding,'detail_url':r.url,'document_candidates':hrefs},'discovered_at':NOW.isoformat()}

def main():
    links=[];seen=set();tele=[]
    variants=[]
    for page in range(MAX_PAGES):
        variants.append({'type':'ContractNotices','top':TOP,'of':'datePublished','od':'desc','m':'0','skip':page*TOP})
    for i,params in enumerate(variants):
        try:r=S.get(SEARCH,params=params,timeout=60);tele.append({'page':i,'url':r.url,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status()
        except Exception as exc:tele.append({'page':i,'error':repr(exc)});continue
        soup=BeautifulSoup(r.text,'html.parser');new=0
        for a in soup.find_all('a',href=True):
            h=a.get('href') or ''
            if not LINK_RE.match(h):continue
            # Collapse lot/subpage to notice root when possible.
            m=re.match(r'(/(?:en|fi|sv)/public/(?:procedure|procurement)/\d+/(?:enotice|notice)/\d+)',h,re.I);h=m.group(1) if m else h
            u=urljoin(BASE,h)
            if u not in seen:seen.add(u);links.append(u);new+=1
        tele[-1]['notice_links']=new
        if i>0 and new==0:break
    rows=[]
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs=[ex.submit(fetch_detail,u) for u in links]
        for f in as_completed(futs):
            x=f.result()
            if x.get('candidate_id'):rows.append(x)
    rows.sort(key=lambda x:x.get('published') or '',reverse=True);cur=[x for x in rows if x.get('current')]
    for fn,data in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'FI_HILMA','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x.get('deadline')) for x in rows),'document_routes':sum(bool((x.get('route') or {}).get('document_candidates')) for x in rows),'generated_at':NOW.isoformat(),'lookback_days':LOOKBACK,'errors':[] if rows else [{'type':'NO_PUBLIC_SEARCH_RESULTS'}],'official_search':SEARCH,'transport':'anonymous public HILMA search/detail fallback; AVP read API remains preferred when a subscription key is configured','telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
