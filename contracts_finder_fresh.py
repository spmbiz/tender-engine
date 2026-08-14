from pathlib import Path
import requests,json,re,time
from datetime import datetime,timezone
from urllib.parse import urljoin

OUT=Path('uk_fresh'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://www.contractsfinder.service.gov.uk/'
KEYS=re.compile(r'\b(website|web site|web development|video|animation|graphic design|creative|editorial|copywriting|content creation|digital content|social media|digital marketing|marketing campaign|photography|videography|translation|transcription|proofreading|printing|print services|communications|audio visual|audiovisual|augmented reality|software development|design services)\b',re.I)
NEG=re.compile(r'\b(construction|building works|architect|civil engineering|mechanical engineering|electrical engineering|cleaning|waste|security services|healthcare|transport services)\b',re.I)
start='2026-06-15T00:00:00Z'; end='2026-08-14T23:59:59Z'
url=BASE+f'Published/Notices/OCDS/Search?publishedFrom={start}&publishedTo={end}&stages=tender&limit=100'
allrels=[]; seen=set()
s=requests.Session(); s.headers['User-Agent']='SPM-Tender-Research/1.0'
for page in range(30):
    r=s.get(url,timeout=40); r.raise_for_status(); data=r.json()
    rels=data.get('releases') or []
    for rel in rels:
        k=rel.get('id') or rel.get('ocid')
        if k not in seen: seen.add(k); allrels.append(rel)
    nxt=(data.get('links') or {}).get('next') or data.get('next')
    if not nxt:
        # Some packages expose pagination cursor separately.
        cur=data.get('cursor') or data.get('nextCursor')
        if cur: nxt=BASE+f'Published/Notices/OCDS/Search?publishedFrom={start}&publishedTo={end}&stages=tender&limit=100&cursor={cur}'
    if not nxt: break
    url=urljoin(BASE,nxt); time.sleep(.3)

cands=[]
now=datetime(2026,8,14,15,18,tzinfo=timezone.utc)
for rel in allrels:
    t=rel.get('tender') or {}; title=t.get('title') or ''; desc=t.get('description') or ''
    text=title+' '+desc
    if not KEYS.search(text) or NEG.search(text): continue
    period=t.get('tenderPeriod') or {}; close=period.get('endDate')
    try: close_dt=datetime.fromisoformat(close.replace('Z','+00:00')) if close else None
    except: close_dt=None
    if close_dt and close_dt<now: continue
    val=(t.get('value') or {}).get('amount')
    try: val=float(val) if val is not None else None
    except: val=None
    # Keep low/unknown value. Up to 200k for discovery, ranking heavily favors <=100k.
    if val and val>200000: continue
    docs=t.get('documents') or []
    urls=[]
    for d in docs:
        u=d.get('url')
        if u: urls.append({'title':d.get('title'),'url':u,'format':d.get('format'),'description':d.get('description')})
    suitability=t.get('suitability') or {}
    cands.append({'id':rel.get('id'),'ocid':rel.get('ocid'),'title':title,'description':desc,'closing':close,'value':val,'currency':(t.get('value') or {}).get('currency'),'procurementMethod':t.get('procurementMethod'),'procurementMethodDetails':t.get('procurementMethodDetails'),'suitability':suitability,'documents':urls,'buyer':[(p.get('name')) for p in (rel.get('parties') or []) if 'buyer' in (p.get('roles') or [])]})

def score(x):
    v=x['value']; sc=0
    if v is None: sc+=15
    elif v<=30000: sc+=35
    elif v<=75000: sc+=30
    elif v<=125000: sc+=22
    else: sc+=10
    if x['documents']: sc+=20
    tx=(x['title']+' '+x['description']).lower()
    if re.search(r'website|video|animation|graphic design|copywriting|content creation|translation|transcription|proofreading',tx): sc+=25
    if (x.get('suitability') or {}).get('sme'): sc+=10
    return sc
cands.sort(key=score,reverse=True)
for x in cands: x['priority']=score(x)
(OUT/'candidates.json').write_text(json.dumps(cands,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'stats.json').write_text(json.dumps({'releases':len(allrels),'candidates':len(cands)},indent=2),encoding='utf-8')
print(json.dumps(cands[:100],indent=2,ensure_ascii=False))
