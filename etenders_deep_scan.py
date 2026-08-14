from pathlib import Path
from playwright.sync_api import sync_playwright
import json,re
from datetime import datetime

OUT=Path('deep_scan'); OUT.mkdir(parents=True,exist_ok=True)
KEYS=re.compile(r'\b(animation|animated|video|videography|film|website|web site|web development|graphic|graphics|creative|editorial|content|copywriting|communications|communication services|social media|digital marketing|marketing services|design services|printing|print services|proofread|translation|transcription|photography|audio visual|audiovisual|augmented reality|virtual reality|software development|training|workshop|exhibition|interpretation|media buying|public relations|survey|research services)\b',re.I)
EXCLUDE=re.compile(r'(architect|civil engineering|mechanical|electrical engineering|construction|road works|surveying services|topographical|laboratory equipment|solar pv|structural engineering|cemetery|bridge rehabilitation)',re.I)
rows=[]

def parse_close(txt):
    # examples: Mon Aug 17 10:00:00 IST 2026; Thu Sep 03 12:00:00 IST 2026
    pat=r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+\w+\s+(2026)\b'
    hits=re.findall(pat,txt)
    ds=[]
    for mon,day,tm,yr in hits:
        try: ds.append(datetime.strptime(f'{mon} {day} {yr} {tm}','%b %d %Y %H:%M:%S'))
        except: pass
    return ds[-1] if ds else None

with sync_playwright() as p:
    b=p.chromium.launch(headless=True); page=b.new_page()
    for pg in range(1,21):
        url=f'https://www.etenders.gov.ie/epps/quickSearchAction.do?T01_ps=100&d-3680175-n=1&d-3680175-o=1&d-3680175-p={pg}&d-3680175-s=eppsId&searchType=cftFTS'
        try:
            page.goto(url,wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(250)
            trs=page.locator('tr')
            for i in range(trs.count()):
                tr=trs.nth(i)
                try: txt=' '.join(tr.inner_text().split())
                except: continue
                if not KEYS.search(txt): continue
                hrefs=[]
                for j in range(tr.locator('a').count()):
                    try:
                        h=tr.locator('a').nth(j).get_attribute('href')
                        if h: hrefs.append(h)
                    except: pass
                rid=None
                for h in hrefs:
                    m=re.search(r'resourceId=(\d+)',h)
                    if m: rid=m.group(1); break
                close=parse_close(txt)
                current=bool(close and close>=datetime(2026,8,14,15,18))
                vals=[]
                for x in re.findall(r'(?<!\d)(\d+(?:\.\d+)?(?:E\d+)?)(?!\d)',txt,re.I):
                    try:
                        v=float(x)
                        if v>=1000: vals.append(v)
                    except: pass
                value=vals[-1] if vals else None
                rows.append({'page':pg,'resourceId':rid,'text':txt,'closing':close.isoformat() if close else None,'current':current,'value_guess':value,'likely_fit':not bool(EXCLUDE.search(txt))})
        except Exception as e: rows.append({'page':pg,'error':repr(e)})
    b.close()
seen=set(); uniq=[]
for r in rows:
    k=r.get('resourceId') or r.get('text')
    if k in seen: continue
    seen.add(k); uniq.append(r)
current=[r for r in uniq if r.get('current') and r.get('likely_fit')]
# prioritize low/unknown value and strong fulfillment terms
boost=re.compile(r'(animation|video|website|graphic|creative|editorial|content|copywriting|social media|digital marketing|printing|proofread|translation|transcription|photography|audio visual|augmented reality|software development)',re.I)
for r in current:
    v=r.get('value_guess'); r['priority']=(30 if boost.search(r.get('text','')) else 0)+(20 if v is None else 25 if v<=75000 else 20 if v<=125000 else 10 if v<=250000 else 0)
current.sort(key=lambda x:(-x.get('priority',0),x.get('value_guess') or 1e99))
(OUT/'all.json').write_text(json.dumps(uniq,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'current.json').write_text(json.dumps(current,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(current[:250],indent=2,ensure_ascii=False))
