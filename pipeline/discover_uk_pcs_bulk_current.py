from __future__ import annotations

import argparse
import json
import os
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
UA = "Tender-Engine/PCS-Bulk-OCDS/1.0 (+official Public Contracts Scotland monthly download)"

# Same live-opportunity notice-type family used by the Kingfisher-pattern API
# collector. Award-only/result-only notice types are excluded from live seeding.
OPPORTUNITY_NOTICE_TYPES = [2, 5, 7, 12, 21, 22, 23, 24, 102]


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


def _post_one(year:int, month:int, notice_type:int, retries:int=4)->dict[str,Any]:
    target_label=month_label(year,month)
    last=None
    for attempt in range(retries):
        try:
            session=requests.Session()
            session.headers.update({"User-Agent":UA,"Accept":"text/html,application/json,*/*"})
            landing=session.get(URL,timeout=90)
            landing.raise_for_status()
            soup=BeautifulSoup(landing.text,"html.parser")
            form=soup.find("form",id="aspnetForm") or soup.find("form")
            if not form: raise RuntimeError("PCS_BULK_FORM_MISSING")
            payload={}
            for node in form.find_all("input"):
                name=node.get("name")
                typ=(node.get("type") or "").lower()
                if name and typ=="hidden": payload[name]=node.get("value") or ""
            select=form.find("select",attrs={"name":"ctl00$maincontent$ddDateRange"})
            if not select: raise RuntimeError("PCS_BULK_DATE_RANGE_MISSING")
            option=None
            for o in select.find_all("option"):
                if target_label == " ".join(o.get_text(" ",strip=True).split()):
                    option=o;break
            if option is None:
                # The official bulk page only exposes a finite historical range.
                # Missing month is explicit, never silently treated as empty.
                raise RuntimeError(f"PCS_BULK_MONTH_NOT_OFFERED:{target_label}")
            payload.update({
                "ctl00$maincontent$rblCollectionType":"0",  # list by date range
                "ctl00$maincontent$ddDateRange":option.get("value") or "",
                "ctl00$maincontent$rblOutputType":"0",      # OCDS
                "ctl00$maincontent$rblDownloadType":"0",    # JSON
                "ctl00$maincontent$rblNoticeTypes":str(notice_type),
                "ctl00$maincontent$buttonDownload":"Download",
            })
            response=session.post(URL,data=payload,timeout=180,allow_redirects=True)
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
                "notice_type":notice_type,"range":option.get("value"),
                "status":response.status_code,"content_type":ctype,
                "bytes":len(response.content),"releases":releases,
            }
        except Exception as exc:
            last=exc
            if attempt < retries-1:
                time.sleep(min(10,1.5*(2**attempt)))
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
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,6))) as pool:
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
                    notice_url=f"https://api.publiccontractsscotland.gov.uk/v1/Notice?id={ocid}" if ocid else URL,
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
        "listing_contract":"PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_V1_KINGFISHER_PATTERN",
        "collector_pattern_source":"open-contracting/kingfisher-collect united_kingdom_scotland/ProactisBase",
        "source_url":URL,"months_requested":len(months),"notice_types":OPPORTUNITY_NOTICE_TYPES,
        "requests_expected":len(tasks),"requests_completed":len(telemetry),
        "source_releases_seen":releases_seen,"raw_materialized":len(rows),"current_materialized":len(rows),
        "publication_window_enumeration_complete":publication_complete,
        "enumeration_exhausted":False,"enumeration_complete":False,
        "live_candidate_capable":bool(rows),"live_coverage_credit_allowed":False,
        "errors":errors,
        "warnings":[] if args.from_2019 else [{"type":"BOUNDED_MONTHLY_BULK_RECONSTRUCTION","months":len(months),"coverage_credit":False}],
        "telemetry":sorted(telemetry,key=lambda x:(x["year"],x["month"],x["notice_type"])),
        "generated_at":NOW.isoformat(),
        "semantics":"Official PCS main-domain monthly bulk download only, using OCDS JSON and the same month x noticeType collection pattern as Open Contracting Kingfisher. Active/future-deadline releases are materialized for recall. Full Current Opportunity coverage remains fail-closed until independently reconciled.",
    }
    (out/"stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    if not publication_complete or not rows: raise SystemExit(3 if errors else 2)

if __name__=="__main__": main()
