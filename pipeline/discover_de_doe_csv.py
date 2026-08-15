from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/DE_DOE"))
OUT.mkdir(parents=True, exist_ok=True)
LOOKBACK_DAYS = max(1, min(14, int(os.getenv("LOOKBACK_DAYS", "7"))))
NOW = datetime.now(timezone.utc)
URL = "https://oeffentlichevergabe.de/api/notice-exports"
S = requests.Session()
S.headers.update({"User-Agent":"Tender-Engine/4.1 (+public procurement research)", "Accept":"application/zip,*/*"})


def clean(v):
    return " ".join(str(v or "").split())


def dt(v):
    if not v:
        return None
    s=clean(v)
    try:
        x=datetime.fromisoformat(s.replace("Z","+00:00"))
        if x.tzinfo is None: x=x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:
        return None


def read_csv(zf, stem):
    wanted = [n for n in zf.namelist() if n.rsplit('/',1)[-1].lower() == f"{stem.lower()}.csv"]
    if not wanted:
        return []
    raw=zf.read(wanted[0]).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))


def key(row,*names):
    for n in names:
        if n in row and row[n] not in (None,""):
            return row[n]
    lower={str(k).lower():v for k,v in row.items()}
    for n in names:
        if n.lower() in lower and lower[n.lower()] not in (None,""):
            return lower[n.lower()]
    return None


def choose_by_notice(rows):
    out={}
    for r in rows:
        nid=clean(key(r,"noticeIdentifier"))
        ver=clean(key(r,"noticeVersion"))
        if not nid: continue
        out.setdefault((nid,ver),[]).append(r)
    return out


def main():
    all_records={}
    telemetry=[]
    for ago in range(LOOKBACK_DAYS):
        day=(NOW-timedelta(days=ago)).date().isoformat()
        try:
            r=S.get(URL,params={"pubDay":day,"format":"csv.zip"},timeout=120)
            if r.status_code==400:
                telemetry.append({"day":day,"status":400,"note":"no export / weekend / not yet published"})
                continue
            r.raise_for_status()
            zf=zipfile.ZipFile(io.BytesIO(r.content))
            notices=read_csv(zf,"notice")
            purposes=choose_by_notice(read_csv(zf,"purpose"))
            orgs=choose_by_notice(read_csv(zf,"organisation"))
            terms=choose_by_notice(read_csv(zf,"submissionTerms"))
            procs=choose_by_notice(read_csv(zf,"procedure"))
            classes=choose_by_notice(read_csv(zf,"classification"))
            telemetry.append({"day":day,"status":200,"bytes":len(r.content),"files":len(zf.namelist()),"notices":len(notices)})
            for n in notices:
                nid=clean(key(n,"noticeIdentifier")); ver=clean(key(n,"noticeVersion"))
                if not nid: continue
                ntype=clean(key(n,"noticeType"))
                # German CSV contract notices use cn-*; keep competition notices only.
                if ntype and not ntype.lower().startswith("cn-"):
                    continue
                k=(nid,ver)
                ps=purposes.get(k,[])
                # prefer notice-level purpose, otherwise first lot purpose
                p=next((x for x in ps if not clean(key(x,"lotIdentifier"))), ps[0] if ps else {})
                os_=orgs.get(k,[])
                buyer=next((x for x in os_ if clean(key(x,"organisationRole")).lower()=="buyer"), os_[0] if os_ else {})
                ts=terms.get(k,[])
                term=ts[0] if ts else {}
                pr=(procs.get(k) or [{}])[0]
                cl=(classes.get(k) or [{}])[0]
                deadline=dt(key(term,"publicOpeningDate"))
                pub=dt(key(n,"publicationDate"))
                title=clean(key(p,"title"))
                rec={
                    "candidate_id":f"DE-DOE:{nid}:{ver or '1'}",
                    "source":"DE_DOE","portal":"DE_DOE","notice_id":nid,
                    "title":title,"buyer":clean(key(buyer,"organisationName")) or None,
                    "deadline":deadline.isoformat() if deadline else None,
                    "published":pub.isoformat() if pub else day,
                    "current":not deadline or deadline>=NOW,
                    "notice_url":f"https://oeffentlichevergabe.de/ui/de/search/details?noticeId={nid}",
                    "estimated_value":key(p,"estimatedValue"),
                    "currency":clean(key(p,"estimatedValueCurrency")) or None,
                    "description":clean(key(p,"description")),
                    "procurement_method":clean(key(pr,"procedureType")) or None,
                    "cpv":clean(key(cl,"mainClassificationCode")) or None,
                    "route":{"document_urls":[]},"discovered_at":NOW.isoformat(),
                }
                all_records[rec["candidate_id"]]=rec
        except Exception as exc:
            telemetry.append({"day":day,"error":repr(exc)})

    rows=list(all_records.values())
    current=[x for x in rows if x.get("current",True)]
    for fn,data in (("raw.jsonl",rows),("current.jsonl",current)):
        with (OUT/fn).open("w",encoding="utf-8") as f:
            for x in data: f.write(json.dumps(x,ensure_ascii=False)+"\n")
    stats={"source":"DE_DOE","raw_materialized":len(rows),"current_materialized":len(current),"lookback_days":LOOKBACK_DAYS,"generated_at":NOW.isoformat(),"errors":[],"official_url":URL,"probe_telemetry":telemetry}
    (OUT/"stats.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows and any("error" in x for x in telemetry):
        raise SystemExit(2)

if __name__=="__main__": main()
