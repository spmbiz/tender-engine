from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL="https://ejn.gov.si/ponudba/pages/aktualno/aktualna_javna_narocila.xhtml"
OUT=Path(os.getenv("DISCOVERY_OUT","discovery/global/SI_EJN"));OUT.mkdir(parents=True,exist_ok=True)
MAX_PAGES=max(1,int(os.getenv("SI_EJN_MAX_PAGES","80")))
TZ=ZoneInfo("Europe/Ljubljana");NOW=datetime.now(TZ)
DEADLINE_RE=re.compile(r"(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})\s+(\d{1,2}:\d{2})")
ID_RE=re.compile(r"\b(?:JN[- ]?\d{3,}|\d{3,}-\d{2}-\d{6})\b",re.I)


def clean(v): return " ".join(str(v or "").split())

def parse_deadline(v):
    m=DEADLINE_RE.search(v or "")
    if not m:return None
    raw=re.sub(r"\s+","",m.group(1))+" "+m.group(2)
    try:return datetime.strptime(raw,"%d.%m.%Y %H:%M").replace(tzinfo=TZ)
    except ValueError:return None

def scrape_rows(page,page_no):
    data=page.locator("table tbody tr").evaluate_all("""rows => rows.map(r => ({
      cells:[...r.querySelectorAll('td')].map(x => (x.innerText||'').trim()),
      links:[...r.querySelectorAll('a[href]')].map(a => ({text:(a.innerText||'').trim(),href:a.href}))
    }))""")
    out=[]
    for item in data:
        cells=[clean(x) for x in item.get("cells",[])]
        if len(cells)<8:continue
        # Canonical table layout: buyer,title,internal id,procedure,eJN date,PJN id,PJN date,deadline,opening,status.
        buyer,title,internal_id=cells[0],cells[1],cells[2]
        procedure=cells[3] if len(cells)>3 else None
        pjn=cells[5] if len(cells)>5 else None
        deadline=parse_deadline(cells[7] if len(cells)>7 else "")
        status=cells[9] if len(cells)>9 else (cells[-1] if cells else "")
        if deadline and deadline<NOW:continue
        if status and "sprejem ponudb" not in status.lower() and any(x in status.lower() for x in ("zaključ","preklic","oddano")):continue
        links=item.get("links") or []
        detail=None
        # Prefer a link whose text is the tender title/internal id, otherwise first non-generic link in row.
        for a in links:
            txt=clean(a.get("text"));href=a.get("href")
            if not href:continue
            if txt in {title,internal_id,pjn} or (title and txt and txt in title):detail=href;break
        if not detail and links:detail=links[0].get("href")
        identity=internal_id or pjn
        if not identity:
            m=ID_RE.search(" | ".join(cells));identity=m.group(0) if m else None
        if not identity:continue
        out.append({
          "candidate_id":f"SI-EJN:{identity}","source":"SI_EJN","portal":"SI_EJN","notice_id":identity,
          "title":title,"buyer":buyer or None,"deadline":deadline.isoformat() if deadline else None,"current":True,
          "notice_url":detail or URL,"description":" | ".join(cells),"procurement_method":procedure or None,
          "currency":"EUR","route":{"detail_url":detail or URL,"public_url":detail or URL,"internal_id":internal_id,"pjn_id":pjn},
          "discovery_page":page_no,"discovered_at":NOW.isoformat(),
        })
    return out

def main():
    by_id={};errors=[];pages=0
    with sync_playwright() as p:
        executable=os.getenv("CHROME_BIN") or None
        browser=p.chromium.launch(headless=True,executable_path=executable,args=["--disable-dev-shm-usage","--no-sandbox"])
        page=browser.new_page(viewport={"width":1440,"height":1000})
        page.goto(URL,wait_until="domcontentloaded",timeout=60000)
        page.wait_for_timeout(1500)
        for pg in range(1,MAX_PAGES+1):
            try:
                rows=scrape_rows(page,pg);pages+=1
                for x in rows:by_id.setdefault(x["candidate_id"],x)
                nxt=page.locator(".ui-paginator-next:not(.ui-state-disabled)")
                if nxt.count()==0:break
                before=page.locator("table tbody tr").first.inner_text(timeout=5000)
                nxt.first.click(timeout=10000)
                page.wait_for_timeout(650)
                try:
                    page.wait_for_function("prev => {const r=document.querySelector('table tbody tr'); return r && (r.innerText||'') !== prev}",arg=before,timeout=10000)
                except Exception:
                    page.wait_for_timeout(1000)
            except Exception as exc:
                errors.append({"page":pg,"error":repr(exc)});break
        browser.close()
    rows=sorted(by_id.values(),key=lambda x:(x.get("deadline") or "9999",x["candidate_id"]))
    for name in ("raw.jsonl","current.jsonl"):
        with (OUT/name).open("w",encoding="utf-8") as f:
            for x in rows:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    stats={"source":"SI_EJN","official_url":URL,"pages_fetched":pages,"current_materialized":len(rows),"errors":errors,"generated_at":NOW.isoformat()}
    (OUT/"stats.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(3)

if __name__=="__main__":main()
