from __future__ import annotations

import asyncio, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from playwright.async_api import async_playwright

OUT=Path(os.getenv("DISCOVERY_OUT","discovery/global/AU_AUSTENDER")); OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
URL="https://www.tenders.gov.au/?event=public.ATM.list"


def clean(v): return " ".join(str(v or "").split())
def pdt(v):
    s=clean(v)
    for fmt in ("%d-%b-%Y %I:%M %p (ACT Local Time)","%d-%b-%Y %I:%M %p","%d-%b-%Y","%d/%m/%Y","%Y-%m-%d"):
        try:return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc)
        except Exception:pass
    return None

def persist(records, telemetry, errors):
    rows=list(records.values()); cur=[x for x in rows if x.get("current",True)]
    for fn,data in (("raw.jsonl",rows),("current.jsonl",cur)):
        with (OUT/fn).open("w",encoding="utf-8") as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    stats={"source":"AU_AUSTENDER","raw_materialized":len(rows),"current_materialized":len(cur),"generated_at":NOW.isoformat(),"errors":errors,"official_url":URL,"telemetry":telemetry}
    (OUT/"stats.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(stats,indent=2,ensure_ascii=False))
    return stats

async def main():
    records={}; telemetry={"url":URL}; errors=[]
    try:
        async with async_playwright() as pw:
            chrome=os.getenv("CHROME_BIN") or None
            browser=await pw.chromium.launch(headless=True, executable_path=chrome)
            page=await browser.new_page(viewport={"width":1440,"height":1000})
            resp=await page.goto(URL,wait_until="domcontentloaded",timeout=90000)
            telemetry["http_status"]=resp.status if resp else None
            await page.wait_for_timeout(2500)
            telemetry["page_title"]=await page.title(); telemetry["html_bytes"]=len(await page.content())
            if resp and resp.status>=400:
                errors.append({"type":"PUBLIC_SOURCE_HTTP_BLOCK","status":resp.status,"message":f"AusTender public listing returned HTTP {resp.status}"})
                await browser.close(); persist(records,telemetry,errors); return
            rows=page.locator("tr"); n=await rows.count(); telemetry["table_rows_seen"]=n
            for i in range(n):
                tr=rows.nth(i); cells=tr.locator("td"); cc=await cells.count()
                if cc<3: continue
                vals=[clean(await cells.nth(j).inner_text()) for j in range(cc)]
                links=tr.locator("a[href]"); lc=await links.count(); href=None; text_link=None
                for j in range(lc):
                    a=links.nth(j); h=await a.get_attribute("href"); t=clean(await a.inner_text())
                    if h and ("ATM" in h.upper() or "ATM" in t.upper() or "view" in h.lower()): href=h; text_link=t; break
                if not href and lc: href=await links.nth(0).get_attribute("href"); text_link=clean(await links.nth(0).inner_text())
                joined=" | ".join(vals); m=re.search(r"\b(?:ATM\s*)?([A-Z0-9][A-Z0-9._/-]{4,})\b", text_link or ""); atm=(m.group(1) if m else clean(vals[0]))
                if not href or not atm or len(joined)<20: continue
                deadline=None
                for dv in reversed([v for v in vals if re.search(r"\b20\d{2}\b",v)]):
                    x=pdt(dv)
                    if x: deadline=x; break
                candidates=[v for v in vals if len(v)>=5 and not re.fullmatch(r"[\d\s:./()-]+",v)]
                title=max(candidates,key=len) if candidates else joined[:500]; link=urljoin("https://www.tenders.gov.au/",href); cid=f"AU:{atm}"
                records[cid]={"candidate_id":cid,"source":"AU_AUSTENDER","portal":"AU_AUSTENDER","notice_id":atm,"title":title,"buyer":None,"deadline":deadline.isoformat() if deadline else None,"published":None,"current":not deadline or deadline>=NOW,"notice_url":link,"description":"","route":{"document_urls":[]},"discovered_at":NOW.isoformat()}
            await browser.close()
    except Exception as exc:
        errors.append({"type":"BROWSER_ERROR","message":repr(exc)})
    persist(records,telemetry,errors)

if __name__=="__main__": asyncio.run(main())
