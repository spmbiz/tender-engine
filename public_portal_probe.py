from pathlib import Path
from urllib.parse import urljoin, urlparse
import json, re, hashlib
from playwright.sync_api import sync_playwright

OUT=Path('public_portal_store'); OUT.mkdir(exist_ok=True)
FILE_RE=re.compile(r'\.(zip|pdf|docx?|xlsx?|xls|pptx?)(?:$|[?#])',re.I)

CASES=[
 {'key':'UNGM','url':'https://www.ungm.org/Public/Notice/302249','direct':['https://www.ungm.org/Public/Notice/DownloadAllDocuments?noticeId=302249']},
 {'key':'IRELAND_ETENDERS','url':'https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId=8763289'},
 {'key':'SCOTLAND_PCS','url':'https://www.publiccontractsscotland.gov.uk/Search/show/Search_View.aspx?ID=FEB549835'},
 {'key':'SAM','url':'https://sam.gov/opp/e00b41d9c473471c97b29c5ce8f8459f/view'},
 {'key':'CANADABUYS','url':'https://canadabuys.canada.ca/en/tender-opportunities?current_tab=t&items_per_page=50&words=website'},
 {'key':'AUSTENDER','url':'https://www.tenders.gov.au/'},
 {'key':'BE_EPROC','url':'https://www.publicprocurement.be/'},
 {'key':'EU_FUNDING_TENDERS','url':'https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search'},
 {'key':'CLIRA','url':'https://clira.io/'},
 {'key':'MERCELL','url':'https://s2c.mercell.com/today/227119'},
]

def sha(b): return hashlib.sha256(b).hexdigest()

def save_file(d,name,b,ct=''):
    name=re.sub(r'[^A-Za-z0-9._() -]+','_',name)[:180] or 'download.bin'
    p=d/name; p.write_bytes(b)
    return {'name':name,'size':len(b),'sha256':sha(b),'content_type':ct}

def looks_binary(ct,cd,url):
    ct=(ct or '').lower(); cd=(cd or '').lower(); u=(url or '').lower()
    return ('attachment' in cd or FILE_RE.search(u) or any(x in ct for x in ['application/pdf','application/zip','application/octet-stream','application/vnd','application/msword'])) and 'text/html' not in ct

results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    ctx=browser.new_context(accept_downloads=True)
    for case in CASES:
        d=OUT/case['key']; d.mkdir(parents=True,exist_ok=True)
        rec={'key':case['key'],'url':case['url'],'status':'UNKNOWN','final_url':None,'http_status':None,'signals':[],'candidate_links':[],'files':[],'error':None}
        page=ctx.new_page()
        # Known direct public endpoints first.
        for du in case.get('direct',[]):
            try:
                rr=ctx.request.get(du,timeout=45000)
                ct=rr.headers.get('content-type',''); cd=rr.headers.get('content-disposition',''); body=rr.body()
                rec['signals'].append(f'direct:{rr.status}:{ct}:{len(body)}')
                if rr.ok and body and looks_binary(ct,cd,du):
                    fn='download_all.zip' if 'zip' in ct.lower() or body[:2]==b'PK' else 'direct_download.bin'
                    rec['files'].append(save_file(d,fn,body,ct))
            except Exception as e: rec['signals'].append('direct_error:'+repr(e))
        try:
            resp=page.goto(case['url'],wait_until='domcontentloaded',timeout=60000)
            page.wait_for_timeout(5000)
            rec['final_url']=page.url; rec['http_status']=resp.status if resp else None
            html=page.content(); text=page.locator('body').inner_text(timeout=15000)
            (d/'page.html').write_text(html,encoding='utf-8'); (d/'page.txt').write_text(text,encoding='utf-8')
            low=text.lower()
            for sig in ['log in','login','sign in','register interest','record your interest','captcha','access denied','forbidden','controlled','register']:
                if sig in low: rec['signals'].append(sig)
            # inspect anchors and attempt obvious public files/document endpoints
            seen=set()
            for a in page.locator('a[href]').all():
                try:
                    href=a.get_attribute('href') or ''; txt=(a.inner_text() or '').strip(); absu=urljoin(page.url,href)
                except Exception: continue
                if absu in seen: continue
                seen.add(absu)
                comb=(absu+' '+txt).lower()
                if FILE_RE.search(absu) or any(t in comb for t in ['download','document','attachment','additional document','contract document','tender document','dossier','pièce','piece']):
                    rec['candidate_links'].append({'text':txt[:160],'url':absu})
                    if FILE_RE.search(absu) or 'download' in absu.lower():
                        try:
                            rr=ctx.request.get(absu,timeout=30000); body=rr.body(); ct=rr.headers.get('content-type',''); cd=rr.headers.get('content-disposition','')
                            if rr.ok and body and looks_binary(ct,cd,absu):
                                fn=Path(urlparse(absu).path).name or f'file_{len(rec["files"])+1}.bin'
                                rec['files'].append(save_file(d,fn,body,ct))
                        except Exception as e: rec['signals'].append('file_error:'+repr(e)[:160])
            if rec['files']: rec['status']='DOWNLOADED_PUBLIC'
            elif rec['http_status'] in (401,403): rec['status']='HTTP_AUTH_OR_BLOCK'
            elif any(x in rec['signals'] for x in ['captcha']): rec['status']='CAPTCHA'
            elif any(x in rec['signals'] for x in ['register interest','record your interest']): rec['status']='REGISTER_INTEREST_REQUIRED'
            elif any(x in rec['signals'] for x in ['log in','login','sign in']): rec['status']='AUTH_SIGNAL'
            elif rec['candidate_links']: rec['status']='DOCUMENT_ROUTE_VISIBLE_NO_DOWNLOAD'
            else: rec['status']='PUBLIC_PAGE_NO_DOCUMENT_ROUTE'
        except Exception as e:
            rec['status']='ERROR'; rec['error']=repr(e)
        finally:
            page.close()
        (d/'manifest.json').write_text(json.dumps(rec,indent=2,ensure_ascii=False),encoding='utf-8')
        results.append(rec)
    browser.close()
(OUT/'summary.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps([{k:r[k] for k in ['key','status','http_status','final_url','signals','candidate_links','files']} for r in results],indent=2,ensure_ascii=False))
