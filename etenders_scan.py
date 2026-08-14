from pathlib import Path
from playwright.sync_api import sync_playwright
import json,re
from datetime import datetime

OUT=Path('fresh_store/ETENDERS_SCAN'); OUT.mkdir(parents=True,exist_ok=True)
KEYS=re.compile(r'\b(design|graphic|marketing|editorial|content|website|web\b|video|animation|translation|proofread|copywriting|communications|social media|digital|media buying|printing|print services|creative|training|research|survey|data entry|administration|artwork|photography|audio visual|audiovisual|interpretation)\b',re.I)
EXCLUDE=re.compile(r'(construction|road works|civil engineering|architectural services|engineering consultancy|medical|pharmaceutical|food|vehicle|cleaning|security guard|waste|electricity|gas supply)',re.I)
rows=[]
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page()
    for pg in range(1,7):
        url=f'https://www.etenders.gov.ie/epps/quickSearchAction.do?T01_ps=100&d-3680175-n=1&d-3680175-o=1&d-3680175-p={pg}&d-3680175-s=eppsId&searchType=cftFTS'
        try:
            page.goto(url,wait_until='domcontentloaded',timeout=45000); page.wait_for_timeout(500)
            trs=page.locator('tr')
            for i in range(trs.count()):
                tr=trs.nth(i)
                try: txt=' '.join(tr.inner_text().split())
                except Exception: continue
                if not KEYS.search(txt): continue
                hrefs=[]
                for j in range(tr.locator('a').count()):
                    try:
                        h=tr.locator('a').nth(j).get_attribute('href')
                        if h: hrefs.append(h)
                    except Exception: pass
                rid=None
                for h in hrefs:
                    m=re.search(r'resourceId=(\d+)',h)
                    if m: rid=m.group(1); break
                # Current tender closing date; keep only Aug/Sep/Oct 2026 visible rows.
                dates=re.findall(r'\b(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-]2026\b',txt)
                current=any(datetime.strptime(d.replace('.','/').replace('-','/'),'%d/%m/%Y')>=datetime(2026,8,14) for d in dates)
                rows.append({'page':pg,'resourceId':rid,'text':txt,'hrefs':hrefs,'dates':dates,'current_after_2026_08_14':current,'likely_fit':not bool(EXCLUDE.search(txt))})
        except Exception as e:
            rows.append({'page':pg,'error':repr(e)})
    b.close()
# canonical de-dupe
seen=set(); out=[]
for r in rows:
    k=r.get('resourceId') or r.get('text')
    if k in seen: continue
    seen.add(k); out.append(r)
(OUT/'scan.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
current=[r for r in out if r.get('current_after_2026_08_14') and r.get('likely_fit')]
(OUT/'current_fit.json').write_text(json.dumps(current,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(current[:120],indent=2,ensure_ascii=False))
