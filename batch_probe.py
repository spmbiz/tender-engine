from pathlib import Path
from urllib.parse import urljoin, urlparse
import json, re, hashlib, subprocess, sys
from playwright.sync_api import sync_playwright

OUT = Path('batch_store')
OUT.mkdir(exist_ok=True)

CASES = [
  {'key':'ETF','notice':'561068-2026','ref':'ETF/2026/OP/0004','url':'https://ted.europa.eu/en/notice/-/detail/561068-2026'},
  {'key':'EHRC','notice':'076279-2026','ref':'EHRC 2627-14','url':'https://www.find-tender.service.gov.uk/Notice/076279-2026'},
  {'key':'OLDHAM','notice':'9dec3987-bb51-4dfd-b4cb-aeaf54aba7ab','ref':'OLDH001-DN825199-81766282','url':'https://www.contractsfinder.service.gov.uk/Notice/9dec3987-bb51-4dfd-b4cb-aeaf54aba7ab'},
  {'key':'GRONINGEN','notice':'551209-2026','ref':'b54add2b-db98-4405-8bc9-08459307ae93','url':'https://ted.europa.eu/en/notice/-/detail/551209-2026'},
  {'key':'APEC','notice':'560517-2026','ref':'26S0030','url':'https://ted.europa.eu/en/notice/-/detail/560517-2026'},
  {'key':'MISTRA','notice':'562593-2026','ref':'019f36f2-96e7-7266-bc6e-4d09e21c0e22','url':'https://ted.europa.eu/en/notice/-/detail/562593-2026'},
  {'key':'BOSA','notice':'561114-2026','ref':'BOSA 0070','url':'https://ted.europa.eu/en/notice/-/detail/561114-2026'},
]

KNOWN_PORTALS = ('procontract.due-north.com','mercell.com','mercell.eu','clira.io','marches-publics.info','achatpublic.com','publicprocurement.be','eprocurement.gov.be','bosa.belgium.be','ec.europa.eu','funding-tenders.ec.europa.eu','etenders.gov.ie')
FILE_RE = re.compile(r'\.(zip|pdf|docx?|xlsx?|xls|pptx?)(?:$|[?#])', re.I)
URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)

def sha(b): return hashlib.sha256(b).hexdigest()

def clean_url(u): return u.rstrip(').,;\'\"')

def is_candidate(href, text, base_domain):
    h=(href or '').lower(); t=(text or '').lower()
    if not href or href.startswith(('mailto:','tel:','javascript:','#')): return False
    dom=urlparse(urljoin('https://'+base_domain+'/',href)).netloc.lower()
    if any(p in dom for p in KNOWN_PORTALS): return True
    if FILE_RE.search(h): return True
    terms=('procurement document','tender document','contract document','documents','dce','download','télécharg','telecharg','pièces','pieces','mercell','procontract','clira','eprocurement','funding')
    return any(x in (h+' '+t) for x in terms) and dom != base_domain

def save_response(case_dir, name, body, headers):
    p=case_dir/name
    p.write_bytes(body)
    return {'name':name,'size':len(body),'sha256':sha(body),'content_type':headers.get('content-type','')}

def probe_page(page, context, case_dir, url, label):
    result={'label':label,'url':url,'status':'OPENED','links':[],'files':[],'signals':[],'error':None}
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(2500)
        html=page.content(); text=page.locator('body').inner_text(timeout=10000)
        (case_dir/f'{label}.html').write_text(html,encoding='utf-8')
        (case_dir/f'{label}.txt').write_text(text,encoding='utf-8')
        low=text.lower()
        for s in ['login','log in','register interest','register your interest','sign in','create an account','connexion','se connecter','inscription','registrera','inloggning']:
            if s in low: result['signals'].append(s)
        # anchors + raw URLs in page text/html
        found=[]
        for a in page.locator('a[href]').all():
            try:
                href=a.get_attribute('href') or ''; txt=(a.inner_text() or '').strip()
                absu=urljoin(page.url,href)
                found.append((absu,txt))
            except Exception: pass
        for raw in URL_RE.findall(html+'\n'+text): found.append((clean_url(raw),'RAW_URL'))
        seen=set()
        for href,txt in found:
            if href in seen: continue
            seen.add(href)
            result['links'].append({'url':href,'text':txt[:200]})
            # direct file attempt
            if FILE_RE.search(href):
                try:
                    r=context.request.get(href,timeout=30000)
                    ct=(r.headers.get('content-type') or '').lower(); cd=(r.headers.get('content-disposition') or '').lower()
                    body=r.body()
                    if r.ok and body and ('text/html' not in ct or 'attachment' in cd):
                        fn=Path(urlparse(href).path).name or f'file_{len(result["files"])+1}.bin'
                        result['files'].append(save_response(case_dir,fn,body,r.headers))
                except Exception as e: result['signals'].append('direct_file_error:'+str(e)[:180])
        result['status']='DOWNLOADED' if result['files'] else ('AUTH_REQUIRED' if any(x in result['signals'] for x in ['login','log in','register interest','register your interest','sign in','create an account','connexion','se connecter','inscription','registrera','inloggning']) else 'OPEN_NO_FILE')
    except Exception as e:
        result['status']='ERROR_RETRYABLE'; result['error']=str(e)
    return result

summary=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(accept_downloads=True)
    page=context.new_page()
    for c in CASES:
        d=OUT/c['key']; d.mkdir(exist_ok=True)
        rec={'case':c,'primary':None,'portals':[],'final_status':'UNKNOWN','files':[]}
        primary=probe_page(page,context,d,c['url'],'primary')
        rec['primary']=primary
        # shortlist external candidate URLs from primary anchors/raw URLs
        base=urlparse(c['url']).netloc.lower(); candidates=[]
        for x in primary.get('links',[]):
            u=x['url']; t=x['text']
            if is_candidate(u,t,base): candidates.append(u)
        # domain-specific known fallbacks from identifiers/text when notice hides link
        if c['key']=='OLDHAM':
            # Primary CF notice normally exposes advert URL; regex from page text/HTML should find it.
            pass
        # de-dupe, avoid obvious social/assets and same primary page
        uniq=[]
        for u in candidates:
            if u not in uniq and u != c['url'] and len(uniq)<8: uniq.append(u)
        for i,u in enumerate(uniq):
            pr=probe_page(page,context,d,u,f'portal_{i+1}')
            rec['portals'].append(pr)
            rec['files'].extend(pr.get('files',[]))
        if rec['files']: rec['final_status']='DOWNLOADED'
        elif any(x['status']=='AUTH_REQUIRED' for x in rec['portals']): rec['final_status']='AUTH_REQUIRED'
        elif any(x['status']=='ERROR_RETRYABLE' for x in rec['portals']): rec['final_status']='ERROR_RETRYABLE'
        elif uniq: rec['final_status']='PORTAL_REACHED_NO_FILE'
        else: rec['final_status']='NO_DCE_LINK_DISCOVERED'
        (d/'manifest.json').write_text(json.dumps(rec,indent=2,ensure_ascii=False),encoding='utf-8')
        summary.append(rec)
    browser.close()

# Positive control: proven Luxembourg adapter.
try:
    cp=subprocess.run([sys.executable,'lux_test.py'],capture_output=True,text=True,timeout=120)
    lux={'key':'LUXEMBOURG_CONTROL','returncode':cp.returncode,'stdout':cp.stdout[-4000:],'stderr':cp.stderr[-2000:]}
except Exception as e: lux={'key':'LUXEMBOURG_CONTROL','error':str(e)}

final={'cases':summary,'luxembourg_control':lux}
(OUT/'summary.json').write_text(json.dumps(final,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({'results':[{'key':r['case']['key'],'status':r['final_status'],'files':len(r['files']),'portal_count':len(r['portals'])} for r in summary],'lux_rc':lux.get('returncode')},indent=2))
