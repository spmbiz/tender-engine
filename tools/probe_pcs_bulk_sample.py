from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.publiccontractsscotland.gov.uk/NoticeDownload/Download.aspx"


def main():
    s=requests.Session()
    s.headers.update({"User-Agent":"Tender-Engine/PCS-Bulk-Sample","Accept":"text/html,application/json,*/*"})
    landing=s.get(URL,timeout=90)
    landing.raise_for_status()
    soup=BeautifulSoup(landing.text,"html.parser")
    form=soup.find("form",id="aspnetForm") or soup.find("form")
    if not form: raise SystemExit("NO_FORM")
    payload={}
    for node in form.find_all("input"):
        name=node.get("name")
        typ=(node.get("type") or "").lower()
        if name and typ=="hidden": payload[name]=node.get("value") or ""
    select=form.find("select",attrs={"name":"ctl00$maincontent$ddDateRange"})
    if not select: raise SystemExit("NO_DATE_RANGE")
    option=None
    for o in select.find_all("option"):
        if "August, 2026" in o.get_text(" ",strip=True):
            option=o;break
    if option is None: option=select.find("option")
    payload.update({
        "ctl00$maincontent$rblCollectionType":"0",
        "ctl00$maincontent$ddDateRange":option.get("value"),
        "ctl00$maincontent$rblOutputType":"0",
        "ctl00$maincontent$rblDownloadType":"0",
        "ctl00$maincontent$rblNoticeTypes":"102",
        "ctl00$maincontent$buttonDownload":"Download",
    })
    r=s.post(URL,data=payload,timeout=120,allow_redirects=True)
    result={
        "schema":"PCS_BULK_SAMPLE_V1",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "landing_status":landing.status_code,
        "post_status":r.status_code,
        "final_url":r.url,
        "selected_range":option.get("value"),
        "notice_type":102,
        "content_type":r.headers.get("content-type"),
        "content_disposition":r.headers.get("content-disposition"),
        "bytes":len(r.content),
        "prefix":r.text[:300] if "text" in (r.headers.get("content-type") or "").lower() or "json" in (r.headers.get("content-type") or "").lower() else None,
    }
    try:
        data=r.json()
        result["json_type"]=type(data).__name__
        if isinstance(data,dict):
            result["keys"]=list(data)[:30]
            rel=data.get("releases")
            result["release_count"]=len(rel) if isinstance(rel,list) else None
            if isinstance(rel,list) and rel:
                result["sample_ocids"]=[str(x.get("ocid") or "") for x in rel[:10] if isinstance(x,dict)]
    except Exception as exc:
        result["json_error"]=repr(exc)
    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_bulk_sample.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
