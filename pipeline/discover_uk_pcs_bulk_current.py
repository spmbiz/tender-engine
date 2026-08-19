from __future__ import annotations

import argparse
import copy
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

try:
    from pipeline.ocds_release_normalizer import release_to_candidate
except ModuleNotFoundError:
    from ocds_release_normalizer import release_to_candidate

URL = "https://www.publiccontractsscotland.gov.uk/NoticeDownload/Download.aspx"
NOW = datetime.now(timezone.utc)
UA = "Tender-Engine/PCS-Bulk-OCDS/1.1 (+official Public Contracts Scotland monthly download)"
OPPORTUNITY_NOTICE_TYPES = [2, 5, 7, 12, 21, 22, 23, 24, 102]
_THREAD = threading.local()


def months_back(count: int) -> list[tuple[int, int]]:
    y, m = NOW.year, NOW.month
    out=[]
    for _ in range(max(1,count)):
        out.append((y,m))
        if m==1: y,m=y-1,12
        else: m-=1
    return out


def months_from_2019() -> list[tuple[int,int]]:
    y,m=2019,1
    out=[]
    while (y,m) <= (NOW.year,NOW.month):
        out.append((y,m))
        if m==12: y,m=y+1,1
        else: m+=1
    return out


def month_label(year:int,month:int)->str:
    return datetime(year,month,1).strftime("%B, %Y")


def _new_worker_context() -> dict[str, Any]:
    session=requests.Session()
    session.headers.update({"User-Agent":UA,"Accept":"text/html,application/json,*/*"})
    landing=session.get(URL,timeout=60)
    landing.raise_for_status()
    soup=BeautifulSoup(landing.text,"html.parser")
    form=soup.find("form",id="aspnetForm") or soup.find("form")
    if not form: raise RuntimeError("PCS_BULK_FORM_MISSING")
    hidden={}
    for node in form.find_all("input"):
        name=node.get("name")
        typ=(node.get("type") or "").lower()
        if name and typ=="hidden": hidden[name]=node.get("value") or ""
    select=form.find("select",attrs={"name":"ctl00$maincontent$ddDateRange"})
    if not select: raise RuntimeError("PCS_BULK_DATE_RANGE_MISSING")
    ranges={
        " ".join(o.get_text(" ",strip=True).split()): (o.get("value") or "")
        for o in select.find_all("option")
        if o.get_text(" ",strip=True)
    }
    return {"session":session,"hidden":hidden,"ranges":ranges,"landing_status":landing.status_code}


def _worker_context(refresh: bool=False) -> dict[str, Any]:
    if refresh or not hasattr(_THREAD,"pcs_bulk_context"):
        old=getattr(_THREAD,"pcs_bulk_context",None)
        if old:
            try: old["session"].close()
            except Exception: pass
        _THREAD.pcs_bulk_context=_new_worker_context()
    return _THREAD.pcs_bulk_context


def _post_one(year:int, month:int, notice_type:int, retries:int=4)->dict[str,Any]:
    target_label=month_label(year,month)
    last=None
    refreshed=0
    for attempt in range(retries):
        try:
            ctx=_worker_context(refresh=attempt>0)
            range_value=ctx["ranges"].get(target_label)
            if range_value is None:
                raise RuntimeError(f"PCS_BULK_MONTH_NOT_OFFERED:{target_label}")
            payload=copy.deepcopy(ctx["hidden"])
            payload.update({
                "ctl00$maincontent$rblCollectionType":"0",
                "ctl00$maincontent$ddDateRange":range_value,
                "ctl00$maincontent$rblOutputType":"0",
                "ctl00$maincontent$rblDownloadType":"0",
                "ctl00$maincontent$rblNoticeTypes":str(notice_type),
                "ctl00$maincontent$buttonDownload":"Download",
            })
            response=ctx["session"].post(URL,data=payload,timeout=120,allow_redirects=True)
            response.raise_for_status()
            ctype=(response.headers.get("content-type") or "").lower()
            if "json" not in ctype and not response.content.lstrip().startswith((b"{",b"[")):
                raise RuntimeError(f"PCS_BULK_NON_JSON:{ctype}:{response.text[:200]!r}")
            data=response.json()
            if not isinstance(data,dict):
                raise RuntimeError(f"PCS_BULK_NON_OBJECT_JSON:{type(data).__name__}")
            releases=data.get("releases") or []
            if not isinstance(releases,list):
                raise RuntimeError("PCS_BULK_RELEASES_NOT_LIST")
            return {
                "year":year,"month":month,"month_label":target_label,
                "notice_type":notice_type,"range":range_value,
                "status":response.status_code,"content_type":ctype,
                "bytes":len(response.content),"releases":releases,
                "worker_form_refreshes":refreshed,
            }
        except Exception as exc:
            last=exc
            if attempt < retries-1:
                refreshed += 1
                time.sleep(min(8,1.25*(2**attempt)))
    raise RuntimeError(f"PCS_BULK_FAILED {target_label} type={notice_type}: {last!r}")


def write_jsonl(path:Path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as fh:
        for row in rows: fh.write(json.dumps(row,ensure_ascii=False)+"\n")


def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=Path(os.getenv("DISCOVERY_OUT","discovery/global/UK_PCS_OCDS")))
    ap.add_argument("--months",type=int,default=int(os.getenv("PCS_BULK_LOOKBACK_MONTHS","36")))
    ap.add_argument("--workers",type=int,default=int(os.getenv("PCS_BULK_WORKERS","4")))
    ap.add_argument("--from-2019",action="store_true",default=os.getenv("DISCOVERY_MODE")=="reconcile")
    args=ap.parse_args()

    months=months_from_2019() if args.from_2019 else months_back(args.months)
    tasks=[(y,m,nt) for y,m in months for nt in OPPORTUNITY_NOTICE_TYPES]
    telemetry=[];errors=[];candidates={};releases_seen=0
    worker_count=max(1,min(args.workers,6))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures={pool.submit(_post_one,y,m,nt):(y,m,nt) for y,m,nt in tasks}
        for future in as_completed(futures):
            y,m,nt=futures[future]
            try: result=future.result()
            except Exception as exc:
                errors.append({"year":y,"month":m,"notice_type":nt,"error":repr(exc)})
                continue
            releases=result.pop("releases")
            releases_seen += len(releases)
            result["release_count"]=len(releases)
            telemetry.append(result)
            for release in releases:
                if not isinstance(release,dict): continue
                ocid=str(release.get("ocid") or "").strip()
                cand=release_to_candidate(
                    release,source="UK_PCS_OCDS",portal="PUBLIC_CONTRACTS_SCOTLAND",
                    notice_url=f"https://www.publiccontractsscotland.gov.uk/search/show/search_view.aspx?ID={ocid}" if ocid else URL,
                    now=NOW,
                )
                if not cand or not cand.get("current"): continue
                status=str(cand.get("tender_status") or "").lower()
                if not cand.get("deadline") and status!="active": continue
                cand["country"]="GB"
                cand["currentness_evidence"]="PCS_OFFICIAL_BULK_OCDS_FUTURE_DEADLINE_OR_ACTIVE_TENDER"
                cand.setdefault("route",{})["pcs_bulk_month"]=f"{y:04d}-{m:02d}"
                cand["route"]["pcs_notice_type"]=nt
                candidates[cand["candidate_id"]]=cand

    out=args.output;out.mkdir(parents=True,exist_ok=True)
    rows=sorted(candidates.values(),key=lambda x:(x.get("deadline") or "9999",x["candidate_id"]))
    write_jsonl(out/"raw.jsonl",rows);write_jsonl(out/"current.jsonl",rows)
    publication_complete=not errors and len(telemetry)==len(tasks)
    stats={
        "source":"UK_PCS_OCDS","portal":"PUBLIC_CONTRACTS_SCOTLAND",
        "listing_contract":"PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_V2_REUSED_FORM_KINGFISHER_PATTERN",
        "collector_pattern_source":"open-contracting/kingfisher-collect united_kingdom_scotland/ProactisBase",
        "source_url":URL,"months_requested":len(months),"notice_types":OPPORTUNITY_NOTICE_TYPES,
        "workers":worker_count,"form_fetch_upper_bound":worker_count + sum(int(x.get("worker_form_refreshes") or 0) for x in telemetry),
        "requests_expected":len(tasks),"requests_completed":len(telemetry),
        "source_releases_seen":releases_seen,"raw_materialized":len(rows),"current_materialized":len(rows),
        "publication_window_enumeration_complete":publication_complete,
        "enumeration_exhausted":False,"enumeration_complete":False,
        "live_candidate_capable":bool(rows),"live_coverage_credit_allowed":False,
        "errors":errors,
        "warnings":[] if args.from_2019 else [{"type":"BOUNDED_MONTHLY_BULK_RECONSTRUCTION","months":len(months),"coverage_credit":False}],
        "telemetry":sorted(telemetry,key=lambda x:(x["year"],x["month"],x["notice_type"])),
        "generated_at":NOW.isoformat(),
        "semantics":"Official PCS main-domain monthly bulk download only, using OCDS JSON and the same month x noticeType collection pattern as Open Contracting Kingfisher. One ASP.NET download form/session is reused per worker to reduce portal load. Active/future-deadline releases are materialized for recall. Full Current Opportunity coverage remains fail-closed until independently reconciled.",
    }
    (out/"stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    if not publication_complete or not rows: raise SystemExit(3 if errors else 2)

if __name__=="__main__": main()
