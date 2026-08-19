from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.eprocurement.gov.cy"
RID = re.compile(r"resourceId=(\d+)", re.I)
CAPTCHA = re.compile(r"captcha|κωδικό captcha|type the code shown", re.I)


def main():
    s = requests.Session()
    s.headers.update({"User-Agent":"Tender-Engine/Cyprus-QuickSearch-Probe","Accept":"text/html,*/*"})
    pages=[]
    seen=set()
    for page in range(1,6):
        url=(
            f"{BASE}/epps/quickSearchAction.do?latest=true&searchSelect=4"
            f"&T01_ps=100&d-3680175-n=1&d-3680175-o=2&d-3680175-p={page}&d-3680175-s=deadline"
        )
        item={"requested_page":page,"url":url}
        try:
            r=s.get(url,timeout=60,allow_redirects=True)
            item["status"]=r.status_code
            item["final_url"]=r.url
            item["captcha"]=bool(CAPTCHA.search(r.text))
            ids=[]
            for rid in RID.findall(r.text):
                if rid not in ids:ids.append(rid)
            item["resource_ids"]=ids[:150]
            item["resource_id_count"]=len(ids)
            item["new_resource_ids"]=sum(1 for x in ids if x not in seen)
            seen.update(ids)
            soup=BeautifulSoup(r.text,"html.parser")
            item["body_sample"]=" ".join(soup.get_text(" ",strip=True).split())[:4000]
        except Exception as exc:
            item["error"]=repr(exc)
        pages.append(item)
    payload={
        "schema":"CYPRUS_QUICKSEARCH_PROBE_V1",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "pages":pages,
        "unique_resource_ids":len(seen),
        "captcha_seen":any(x.get("captcha") for x in pages),
        "progress_proven":len(seen)>0 and sum(1 for x in pages if (x.get("new_resource_ids") or 0)>0)>=2,
    }
    Path("control").mkdir(exist_ok=True)
    Path("control/cyprus_quicksearch_probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
