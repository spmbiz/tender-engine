from __future__ import annotations

import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv("DISCOVERY_OUT","discovery/global/QC_SEAO")); OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
API="https://www.donneesquebec.ca/recherche/api/3/action/package_show"
S=requests.Session(); S.headers.update({"User-Agent":"Tender-Engine/4.1 (+public procurement research)"})


def clean(v): return " ".join(str(v or "").split())
def pdt(v):
    if not v: return None
    try:
        x=datetime.fromisoformat(str(v).replace("Z","+00:00"));
        if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:return None

def iter_objs(o):
    if isinstance(o,dict):
        if isinstance(o.get("releases"),list):
            yield from (x for x in o["releases"] if isinstance(x,dict))
        elif any(k in o for k in ("ocid","tender","buyer","parties")): yield o
        else:
            for v in o.values(): yield from iter_objs(v)
    elif isinstance(o,list):
        for v in o: yield from iter_objs(v)

def resource_end_date(name):
    nums=re.findall(r"20\d{6}",name or "")
    return max(nums) if nums else "00000000"

def main():
    pkg=S.get(API,params={"id":"systeme-electronique-dappel-doffres-seao"},timeout=60);pkg.raise_for_status()
    resources=((pkg.json().get("result") or {}).get("resources") or [])
    cand=[]
    for r in resources:
        name=clean(r.get("name") or r.get("description")); url=clean(r.get("url")); fmt=clean(r.get("format")).lower()
        if not url or not (fmt=="json" or url.lower().endswith(".json")): continue
        # Dataset warns its UI sorting can be degraded; derive recency from the date embedded in filename.
        if "hebdo_" not in name.lower(): continue
        cand.append((resource_end_date(name), name, url))
    cand.sort(reverse=True)
    picked=cand[:2]
    records={}
    for _,name,url in picked:
        r=S.get(url,timeout=180);r.raise_for_status(); data=r.json()
        for rel in iter_objs(data):
            tender=rel.get("tender") or {}; period=tender.get("tenderPeriod") or {}
            end=pdt(period.get("endDate")); pub=pdt(rel.get("date") or tender.get("datePublished"))
            status=clean(tender.get("status")).lower()
            rid=rel.get("ocid") or rel.get("id") or tender.get("id")
            title=tender.get("title") or rel.get("title") or ""
            if not rid and not title: continue
            parties=rel.get("parties") or []
            buyers=[x.get("name") for x in parties if isinstance(x,dict) and "buyer" in (x.get("roles") or []) and x.get("name")]
            b=rel.get("buyer") or {}; buyer=b.get("name") if isinstance(b,dict) else None
            docs=[d.get("url") for d in tender.get("documents") or [] if isinstance(d,dict) and d.get("url")]
            cur=(not end or end>=NOW) and status not in {"complete","cancelled","unsuccessful","withdrawn"}
            cid=f"QC-SEAO:{clean(rid)}" if rid else f"QC-SEAO:{abs(hash((title,buyer,str(end))))}"
            value=tender.get("value") if isinstance(tender.get("value"),dict) else {}
            records[cid]={"candidate_id":cid,"source":"QC_SEAO","portal":"QC_SEAO","notice_id":clean(rid),"ocid":clean(rel.get("ocid")) or None,"title":clean(title),"buyer":clean(buyer or (buyers[0] if buyers else None)) or None,"deadline":end.isoformat() if end else None,"published":pub.isoformat() if pub else None,"current":cur,"notice_url":None,"estimated_value":value.get("amount"),"currency":value.get("currency") or "CAD","description":clean(tender.get("description")),"procurement_method":tender.get("procurementMethodDetails") or tender.get("procurementMethod"),"route":{"document_urls":docs},"discovered_at":NOW.isoformat()}
    rows=list(records.values()); current=[x for x in rows if x.get("current",True)]
    for fn,data in (("raw.jsonl",rows),("current.jsonl",current)):
        with (OUT/fn).open("w",encoding="utf-8") as f:
            for x in data:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    stats={"source":"QC_SEAO","raw_materialized":len(rows),"current_materialized":len(current),"generated_at":NOW.isoformat(),"errors":[],"official_api":API,"resources_picked":[x[1] for x in picked]}
    (OUT/"stats.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8"); print(json.dumps(stats,indent=2,ensure_ascii=False))

if __name__=="__main__":main()
