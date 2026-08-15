from __future__ import annotations

import json, os, re, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/FI_HILMA'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);LOOKBACK=max(7,min(90,int(os.getenv('LOOKBACK_DAYS','30'))));TOP=max(25,min(100,int(os.getenv('FI_TOP','75'))));MAX_PAGES=max(1,min(12,int(os.getenv('FI_MAX_PAGES','5'))));MAX_DETAILS=max(25,min(300,int(os.getenv('FI_MAX_DETAILS','100'))))
BASE='https://www.hankintailmoitukset.fi';SEARCH=BASE+'/en/search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.4 (+public procurement research)','Accept':'text/html,application/xhtml+xml'})
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
    # Rendered HILMA often puts the value on the next line; permit punctuation/whitespace.
    for label in labels:
        m=re.search(re.escape(label)+r'\s*[:\-]?\s*([^\n]{1,500})',text,re.I)
        if m and clean(m.group(1)):return clean(m.group(1))
    return None

def normalize_notice_link(h):
    if not h:return None
    if h.startswith(('http://','https://')):
        try:
            if 'hankintailmoitukset.fi' not in h.lower():return None
            h='/'+'/'.join(h.split('/',3)[3:]) if h.count('/')>=3 else h
        except Exception:return None
    if not LINK_RE.match(h):return None
    m=re.match(r'(/(?:en|fi|sv)/public/(?:procedure|procurement)/\d+/(?:enotice|notice)/\d+)',h,re.I)
    return urljoin(BASE,m.group(1) if m else h)

def chrome_path():return os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')

def rendered_search_links(params,tele_entry):
    chrome=chrome_path()
    if not chrome:tele_entry['browser_error']='NO_SYSTEM_CHROME';return []
    pw=browser=page=None;links=[];net=[]
    try:
        from playwright.sync_api import sync_playwright
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);page=browser.new_page()
        def on_response(resp):
            try:
                ct=(resp.headers.get('content-type') or '').lower()
                if 'json' in ct and 'cdn.hankintailmoitukset.fi/files/sdk/' not in resp.url:net.append({'url':resp.url,'status':resp.status,'content_type':ct})
            except Exception:pass
        page.on('response',on_response)
        page.goto(SEARCH+'?'+urlencode(params,doseq=True),wait_until='domcontentloaded',timeout=60000)
        try:page.wait_for_load_state('networkidle',timeout=12000)
        except Exception:page.wait_for_timeout(3000)
        hrefs=page.eval_on_selector_all('a[href]','els => els.map(a => a.getAttribute("href") || a.href)') or []
        for h in hrefs:
            u=normalize_notice_link(str(h))
            if u:links.append(u)
        tele_entry.update({'browser_url':page.url,'browser_href_count':len(hrefs),'browser_notice_links':len(set(links)),'browser_json_responses':net[:40]})
    except Exception as exc:tele_entry['browser_error']=repr(exc)
    finally:
        try:
            if page:page.close()
        except Exception:pass
        try:
            if browser:browser.close()
        except Exception:pass
        try:
            if pw:pw.stop()
        except Exception:pass
    return list(dict.fromkeys(links))

def record_from_rendered(url,text,href_pairs):
    text=text or ''
    # Headline is usually before metadata; fall back to explicit title labels.
    title=label_after(text,'Title TED BT-21: Title','Title of the procurement','Ilmoituksen nimi TED BT-21: Nimi','Hankinnan nimi')
    if not title:
        lines=[clean(x) for x in text.splitlines() if clean(x)]
        title=next((x for x in lines if len(x)>12 and x.lower() not in {'hilma','procurement notices'} and not x.lower().startswith(('home','search','published'))),None)
    buyer=label_after(text,'Organisation Name TED BT-500: Organisation Name','Organisaation virallinen nimi TED BT-500: Organisaation nimi','Organisation Name','Contracting authority','Hankintayksikkö')
    pubtxt=label_after(text,'Published in Hilma','Julkaistu Hilmassa','Publicerad i Hilma','Publication date');published=dtparse(pubtxt or '')
    deadline=None
    for label in ('Time limit for receipt of tenders','Time limit for submission','Tenders or requests to participate due','Tarjousten tai osallistumishakemusten vastaanottamisen määräaika','Tarjousten vastaanottamisen määräaika','Määräaika'):
        p=text.lower().find(label.lower())
        if p>=0:
            deadline=dtparse(text[p:p+500])
            if deadline:break
    notice_id=label_after(text,'Notice Hilma-number','Ilmoituksen Hilma-numero','HILMA number','Hilma number')
    ted=label_after(text,'TED number','Ilmoituksen TED-numero');procedure_id=label_after(text,'Procurement procedure identifier','Hankintamenettelyn tunniste','Procedure identifier')
    cpv=[]
    for m in re.finditer(r'\b(\d{8})\b',text):
        if m.group(1) not in cpv:cpv.append(m.group(1))
        if len(cpv)>=20:break
    hrefs=[]
    for href,label in href_pairs or []:
        href=urljoin(url,href or '')
        if href.startswith('http') and (DOC_HINT.search(href) or DOC_HINT.search(label or '') or ('hankintailmoitukset.fi' not in href.lower() and href != url)):hrefs.append(href)
    for m in re.findall(r'https?://[^\s<>"\']+',text):
        u=m.rstrip(').,;')
        if DOC_HINT.search(u):hrefs.append(u)
    hrefs=list(dict.fromkeys(hrefs))[:60]
    direct=[u for u in hrefs if re.search(r'\.(pdf|zip|7z|docx?|xlsx?|pptx?)(?:[?#]|$)',u,re.I)]
    proceeding=next((u for u in hrefs if u not in direct and 'hankintailmoitukset.fi' not in u.lower()),None) or url
    current=bool(deadline and deadline>=NOW)
    if not deadline and published:current=published>=NOW-timedelta(days=LOOKBACK)
    # No dates means unresolved, not automatically current.
    valid=bool(title and title.lower()!='hilma' and (notice_id or procedure_id or buyer or published or deadline or len(text)>2000))
    rid=notice_id or procedure_id or re.sub(r'\D+','-',url).strip('-')[-40:]
    return {'candidate_id':f'FI-HILMA:{rid}','source':'FI_HILMA','portal':'FI_HILMA','notice_id':notice_id,'ted_number':ted,'procedure_id':procedure_id,'title':title or 'UNKNOWN','buyer':buyer,'deadline':deadline.isoformat() if deadline else None,'published':published.isoformat() if published else None,'current':current,'notice_url':url,'cpv':cpv,'description':'','route':{'document_urls':direct,'proceeding_url':proceeding,'detail_url':url,'document_candidates':hrefs},'evidence_state':'RENDERED_DETAIL' if valid else 'DETAIL_UNRESOLVED','discovered_at':NOW.isoformat()}

def render_details(urls,tele):
    chrome=chrome_path();rows=[]
    if not chrome:return rows,[{'type':'NO_SYSTEM_CHROME_FOR_DETAILS'}]
    pw=browser=context=page=None;errors=[]
    try:
        from playwright.sync_api import sync_playwright
        pw=sync_playwright().start();browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox']);context=browser.new_context();page=context.new_page()
        for i,url in enumerate(urls[:MAX_DETAILS]):
            try:
                page.goto(url,wait_until='domcontentloaded',timeout=45000)
                try:page.wait_for_load_state('networkidle',timeout=7000)
                except Exception:page.wait_for_timeout(1200)
                text=page.locator('body').inner_text(timeout=8000)
                href_pairs=page.eval_on_selector_all('a[href]','els => els.map(a => [a.href,(a.innerText||a.textContent||"").trim()])') or []
                rec=record_from_rendered(page.url,text,href_pairs);rows.append(rec)
                if i<3:tele.append({'detail_sample':i,'url':url,'resolved_url':page.url,'text_chars':len(text),'hrefs':len(href_pairs),'title':rec.get('title'),'deadline':rec.get('deadline'),'route_docs':len((rec.get('route') or {}).get('document_candidates') or [])})
            except Exception as exc:errors.append({'url':url,'error':repr(exc)})
    finally:
        try:
            if page:page.close()
        except Exception:pass
        try:
            if browser:browser.close()
        except Exception:pass
        try:
            if pw:pw.stop()
        except Exception:pass
    return rows,errors

def main():
    links=[];seen=set();tele=[]
    for page_no in range(MAX_PAGES):
        params={'type':'ContractNotices','top':TOP,'of':'datePublished','od':'desc','m':'0','skip':page_no*TOP,'oldNr':'','eformNr':''};entry={'page':page_no}
        try:
            r=S.get(SEARCH,params=params,timeout=60);entry.update({'url':r.url,'status':r.status_code,'bytes':len(r.content)});r.raise_for_status();soup=BeautifulSoup(r.text,'html.parser');http_links=[]
            for a in soup.find_all('a',href=True):
                u=normalize_notice_link(a.get('href') or '')
                if u:http_links.append(u)
            entry['http_notice_links']=len(set(http_links));page_links=list(dict.fromkeys(http_links))
        except Exception as exc:entry['http_error']=repr(exc);page_links=[]
        if not page_links:page_links=rendered_search_links(params,entry)
        new=0
        for u in page_links:
            if u not in seen:seen.add(u);links.append(u);new+=1
        entry['notice_links']=new;tele.append(entry)
        if page_no>0 and new==0:break
    rows,detail_errors=render_details(links,tele)
    # Drop shell/unresolved records from the live materialization; retain counts/errors in stats instead of inventing data.
    valid=[x for x in rows if x.get('evidence_state')=='RENDERED_DETAIL'];cur=[x for x in valid if x.get('current')]
    for fn,data in (('raw.jsonl',valid),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'FI_HILMA','raw_materialized':len(valid),'current_materialized':len(cur),'search_notice_links':len(links),'rendered_details':len(rows),'unresolved_details':len(rows)-len(valid)+len(detail_errors),'deadline_parsed':sum(bool(x.get('deadline')) for x in valid),'published_parsed':sum(bool(x.get('published')) for x in valid),'document_routes':sum(bool((x.get('route') or {}).get('document_candidates')) for x in valid),'generated_at':NOW.isoformat(),'lookback_days':LOOKBACK,'errors':detail_errors[:20] if valid else ([{'type':'NO_VALID_RENDERED_DETAIL_RECORDS'}]+detail_errors[:20]),'official_search':SEARCH,'transport':'anonymous public HILMA SPA search + rendered public notice detail; AVP read API remains preferred when a subscription key is configured','telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not valid:raise SystemExit(2)
if __name__=='__main__':main()
