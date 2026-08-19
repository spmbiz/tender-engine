from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.publiccontractsscotland.gov.uk/NoticeDownload/Download.aspx"


def clean(v):
    return " ".join(str(v or "").split())


def main():
    s = requests.Session()
    s.headers.update({"User-Agent":"Tender-Engine/PCS-Bulk-Probe","Accept":"text/html,*/*"})
    r = s.get(URL, timeout=90)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    forms=[]
    for form in soup.find_all("form"):
        controls=[]
        for node in form.find_all(["input","select","button"]):
            meta={
                "tag":node.name,
                "name":node.get("name"),
                "id":node.get("id"),
                "type":node.get("type"),
                "value":node.get("value"),
                "text":clean(node.get_text(" ",strip=True)),
            }
            if node.name=="select":
                meta["options"]=[{
                    "value":o.get("value"),
                    "text":clean(o.get_text(" ",strip=True)),
                    "selected":o.has_attr("selected"),
                } for o in node.find_all("option")[:80]]
            controls.append(meta)
        forms.append({
            "action":urljoin(r.url, form.get("action") or r.url),
            "method":clean(form.get("method") or "get").lower(),
            "id":form.get("id"),
            "controls":controls,
        })
    payload={
        "schema":"PCS_BULK_FORM_PROBE_V1",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "status":r.status_code,
        "final_url":r.url,
        "html_bytes":len(r.content),
        "forms":forms,
    }
    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_bulk_form_probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
