from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://www.uvo.gov.sk"
LIST = BASE + "/vyhladavanie/vyhladavanie-zakaziek"
OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/SK_UVO"))
OUT.mkdir(parents=True, exist_ok=True)
LOOKBACK_DAYS = max(1, int(os.getenv("LOOKBACK_DAYS", "3")))
PAGE_LIMIT = max(1, int(os.getenv("SK_UVO_MAX_PAGES", "8")))
PAGE_SIZE = 100
TZ = ZoneInfo("Europe/Bratislava")
NOW = datetime.now(TZ)
CUTOFF = (NOW - timedelta(days=LOOKBACK_DAYS)).date()
DETAIL_RE = re.compile(r"/vyhladavanie/vyhladavanie-zakaziek/detail/(\d+)", re.I)
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
S = requests.Session()
S.headers.update({"User-Agent": "Tender-Engine/6.1 (+public procurement research; official UVO public search)"})


def clean(v):
    return " ".join(str(v or "").split())


def get(url, params=None):
    for attempt in range(4):
        try:
            r = S.get(url, params=params, timeout=45, allow_redirects=True)
            if r.status_code in (408,425,429) or r.status_code >= 500:
                if attempt < 3:
                    time.sleep(min(10, 2**attempt))
                    continue
            r.raise_for_status(); return r
        except Exception:
            if attempt == 3: raise
            time.sleep(min(8,2**attempt))
    raise RuntimeError(url)


def parse_date(text):
    m = DATE_RE.search(text or "")
    if not m: return None
    try: return datetime.strptime(m.group(1), "%d.%m.%Y").date()
    except ValueError: return None


def parse_page(html, final_url, page_no):
    soup=BeautifulSoup(html,"html.parser")
    rows=[]
    oldest=None
    for tr in soup.find_all("tr"):
        a=None; rid=None
        for link in tr.find_all("a",href=True):
            m=DETAIL_RE.search(link.get("href") or "")
            if m:
                a=link;rid=m.group(1);break
        if not rid: continue
        cells=[clean(td.get_text(" ",strip=True)) for td in tr.find_all("td")]
        if len(cells)<5: continue
        updated=parse_date(cells[4])
        if updated and (oldest is None or updated<oldest): oldest=updated
        if updated and updated<CUTOFF: continue
        title=clean(a.get_text(" ",strip=True)) or cells[0]
        buyer=cells[1] if len(cells)>1 else None
        cpv=cells[2] if len(cells)>2 else None
        nuts=cells[3] if len(cells)>3 else None
        detail=urljoin(final_url,a.get("href"))
        rows.append({
            "candidate_id":f"SK-UVO:{rid}","source":"SK_UVO","portal":"SK_UVO","notice_id":rid,
            "title":title,"buyer":buyer or None,"deadline":None,"current":True,"notice_url":detail,
            "description":" | ".join(cells),"cpv":cpv or None,"nuts":nuts or None,"currency":"EUR",
            "published_at":updated.isoformat() if updated else None,
            "route":{"detail_url":detail,"public_url":detail,"uvo_id":rid,"external_submission_expected":True},
            "discovery_page":page_no,"discovered_at":NOW.isoformat(),
        })
    return rows,oldest


def main():
    by_id={};errors=[];pages=0
    for pg in range(1,PAGE_LIMIT+1):
        try:
            r=get(LIST,params={"limit":PAGE_SIZE,"page":pg})
            recs,oldest=parse_page(r.text,r.url,pg);pages+=1
            for x in recs: by_id.setdefault(x["candidate_id"],x)
            if oldest and oldest<CUTOFF: break
        except Exception as exc:
            errors.append({"page":pg,"error":repr(exc)})
            if not by_id: continue
            break
    rows=sorted(by_id.values(),key=lambda x:(x.get("published_at") or "",x["candidate_id"]),reverse=True)
    for name in ("raw.jsonl","current.jsonl"):
        with (OUT/name).open("w",encoding="utf-8") as f:
            for x in rows: f.write(json.dumps(x,ensure_ascii=False)+"\n")
    stats={"source":"SK_UVO","official_url":LIST,"lookback_days":LOOKBACK_DAYS,"pages_fetched":pages,"current_materialized":len(rows),"errors":errors,"generated_at":NOW.isoformat()}
    (OUT/"stats.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows: raise SystemExit(3)

if __name__=="__main__": main()
