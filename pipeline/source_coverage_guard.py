from __future__ import annotations

import argparse
import json
from pathlib import Path

GLOBAL_PACKS = [
    "discovery-ted",
    "discovery-global-ca-canadabuys","discovery-global-fr-boamp","discovery-global-qc-seao",
    "discovery-global-au-austender","discovery-global-nz-gets","discovery-global-de-doe",
    "discovery-global-es-placsp","discovery-global-us-sam-bulk","discovery-global-nl-tenderned-rss",
    "discovery-global-gr-khmdhs","discovery-global-pl-bzp","discovery-global-lv-iub",
    "discovery-global-ch-simap","discovery-global-no-doffin","discovery-global-fi-hilma",
    "discovery-global-pt-base-open","discovery-global-dk-udbud-public","discovery-global-cz-zakazky-gov",
    "discovery-global-it-anac-delta","discovery-global-cyprus-epps","discovery-global-malta-epps",
    "discovery-global-lux-pmp","discovery-global-si-ejn","discovery-global-sk-uvo","discovery-global-ee-rhr",
    "discovery-global-world-bank-procurement","discovery-global-za-etenders-ocds","discovery-global-uk-pcs-ocds",
    "discovery-global-uk-fts-ocds","discovery-global-lt-cvp-api","discovery-global-ungm-public",
]
STRICT_NONZERO_SOURCES={
    "AU_AUSTENDER","CYPRUS_EPPS","MALTA_EPPS","LUX_PMP","SI_EJN","SK_UVO","EE_RHR",
    "WORLD_BANK_PROCUREMENT","ZA_ETENDERS_OCDS","UK_PCS_OCDS","UK_FTS_OCDS","LT_CVP_API","UNGM_PUBLIC",
}
STRICT_EXHAUSTION_SOURCES={"TED","LT_CVP_API","AU_AUSTENDER","CYPRUS_EPPS","MALTA_EPPS","UNGM_PUBLIC","UK_PCS_OCDS","ZA_ETENDERS_OCDS"}
EXTERNAL_REQUIRED_LANES=[]

def required_sharded(mode):
    mode=(mode or "delta").lower()
    return {"contracts_finder":[f"discovery-contracts-finder-{i}" for i in range(8)],"ireland_etenders":[f"discovery-ie-{i}" for i in range(10 if mode=="reconcile" else 4)]}
def load(path):
    try:return json.loads(path.read_text(encoding="utf-8",errors="replace"))
    except Exception:return None

def pcs_contract_health(obj,path,bad):
    """Validate PCS using the proof contract that actually produced the pack."""
    listing=str(obj.get("listing_contract") or "")
    source=str(obj.get("source") or "").upper()
    if listing.startswith("PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_"):
        # The primary lane enumerates official PCS month x noticeType OCDS
        # downloads. Browser-navigation/page-total proofs are irrelevant for the
        # publication partition itself. A reconciled V4 pack, however, must also
        # carry an independently proven Current Opportunity registry match.
        expected=obj.get("requests_expected")
        completed=obj.get("requests_completed")
        if obj.get("publication_window_enumeration_complete") is not True:
            bad.append({"path":str(path),"reason":"PCS_BULK_PUBLICATION_PARTITIONS_INCOMPLETE","source":source,"listing_contract":listing})
        if expected is not None and completed is not None and int(completed)!=int(expected):
            bad.append({"path":str(path),"reason":"PCS_BULK_REQUEST_COUNT_MISMATCH","source":source,"expected":expected,"completed":completed})
        if not obj.get("notice_types") or 101 not in [int(x) for x in obj.get("notice_types") if str(x).isdigit()]:
            bad.append({"path":str(path),"reason":"PCS_BULK_WEBSITE_CONTRACT_NOTICE_101_MISSING","source":source})
        if "_V4_DIRECT_CURRENT_RECONCILED" in listing:
            rec=obj.get("current_universe_reconciliation") if isinstance(obj.get("current_universe_reconciliation"),dict) else {}
            if rec.get("coverage_complete") is not True:
                bad.append({"path":str(path),"reason":"PCS_CURRENT_UNIVERSE_RECONCILIATION_INCOMPLETE","source":source})
            if rec.get("direct_current_contract_complete") is not True:
                bad.append({"path":str(path),"reason":"PCS_DIRECT_CURRENT_CONTRACT_INCOMPLETE","source":source})
            if rec.get("all_official_current_matched_to_bulk") is not True:
                bad.append({"path":str(path),"reason":"PCS_OFFICIAL_CURRENT_NOT_FULLY_MATCHED_TO_BULK","source":source,"missing":rec.get("direct_missing_from_bulk")})
            try:
                missing=int(rec.get("direct_missing_from_bulk") or 0)
            except Exception:
                missing=-1
            if missing != 0:
                bad.append({"path":str(path),"reason":"PCS_DIRECT_CURRENT_MISSING_FROM_BULK","source":source,"missing":rec.get("direct_missing_from_bulk")})
        return

    # Legacy browser/direct-post PCS contracts remain guarded by the old proof:
    # Current Opportunity filtering must be proven before paging, and page totals
    # must remain stable. This prevents a stale All Notices page 1 from being
    # treated as the filtered universe.
    telemetry=obj.get("telemetry") if isinstance(obj.get("telemetry"),dict) else {}
    filtered_search_proven=(
        obj.get("filtered_current_search_proven") is True
        or telemetry.get("search_navigation_proven") is True
        or obj.get("direct_filtered_post_proven") is True
    )
    if not filtered_search_proven:
        bad.append({"path":str(path),"reason":"PCS_FILTERED_SEARCH_PROOF_MISSING","source":source,"listing_contract":listing})
    page_rows=telemetry.get("pages") if isinstance(telemetry.get("pages"),list) else []
    page_totals=[x.get("total_pages") for x in page_rows if isinstance(x,dict) and x.get("total_pages") is not None]
    if page_totals and len(set(page_totals))>1:
        bad.append({"path":str(path),"reason":"PCS_FILTERED_PAGE_TOTAL_NOT_STABLE","source":source,"page_totals_seen":page_totals[:20]})

def stats_health(pack_dir):
    stats_files=sorted(pack_dir.rglob("stats.json"))
    if not stats_files:return {"status":"MISSING_STATS","stats_files":[]}
    bad=[]
    for path in stats_files:
        obj=load(path)
        if not isinstance(obj,dict):bad.append({"path":str(path),"reason":"UNREADABLE_STATS"});continue
        if obj.get("errors"):bad.append({"path":str(path),"reason":"ERRORS_PRESENT","value":obj.get("errors")})
        if obj.get("error"):bad.append({"path":str(path),"reason":"ERROR_PRESENT","value":obj.get("error")})
        status=str(obj.get("status") or "").upper()
        if status in {"ERROR","FAILED","BLOCKED","PARTIAL_ERROR"}:bad.append({"path":str(path),"reason":f"STATUS_{status}"})
        if obj.get("truncated_by_page_cap"):bad.append({"path":str(path),"reason":"TRUNCATED_BY_PAGE_CAP"})
        if obj.get("truncated_by_runtime_budget"):bad.append({"path":str(path),"reason":"TRUNCATED_BY_RUNTIME_BUDGET"})
        source=str(obj.get("source") or "").upper()
        if obj.get("live_candidate_capable") is False or obj.get("live_coverage_credit_allowed") is False:
            bad.append({"path":str(path),"reason":"NOT_LIVE_CANDIDATE_SOURCE","source":source or "UNKNOWN"})
        if source in STRICT_NONZERO_SOURCES and obj.get("current_materialized") is not None and int(obj.get("current_materialized") or 0)==0:
            bad.append({"path":str(path),"reason":"ZERO_CURRENT_MATERIALIZED","source":source})
        if source=="UK_PCS_OCDS":pcs_contract_health(obj,path,bad)
        if source in STRICT_EXHAUSTION_SOURCES:
            complete=obj.get("enumeration_complete")
            exhausted=obj.get("enumeration_exhausted",obj.get("exhausted"))
            if complete is False:bad.append({"path":str(path),"reason":"ENUMERATION_INCOMPLETE","source":source})
            elif complete is None and exhausted is not True:bad.append({"path":str(path),"reason":"NO_EXHAUSTION_PROOF","source":source})
            elif complete is None and exhausted is True and obj.get("errors"):bad.append({"path":str(path),"reason":"EXHAUSTION_WITH_ERRORS","source":source})
    exit_files=sorted(pack_dir.rglob("adapter_exit_code.txt"))
    for path in exit_files:
        try:rc=int(path.read_text(encoding="utf-8",errors="replace").strip())
        except Exception:bad.append({"path":str(path),"reason":"UNREADABLE_ADAPTER_EXIT_CODE"});continue
        if rc!=0:bad.append({"path":str(path),"reason":"ADAPTER_EXIT_NONZERO","value":rc})
    return {"status":"DEGRADED" if bad else "OK","stats_files":[str(x) for x in stats_files],"adapter_exit_files":[str(x) for x in exit_files],"problems":bad}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default="discovery-download");ap.add_argument("--out",default="merged/source_coverage.json");ap.add_argument("--mode",default="delta",choices=["delta","reconcile"]);ap.add_argument("--external-present",default="");ap.add_argument("--strict",action="store_true");args=ap.parse_args()
    root=Path(args.root);existing_dirs={p.name:p for p in root.iterdir() if p.is_dir()} if root.exists() else {};expected_packs=list(GLOBAL_PACKS);sharded=required_sharded(args.mode)
    for packs in sharded.values():expected_packs.extend(packs)
    missing=[name for name in expected_packs if name not in existing_dirs];health={};degraded=[]
    for name in expected_packs:
        if name not in existing_dirs:continue
        h=stats_health(existing_dirs[name]);health[name]=h
        if h["status"]!="OK":degraded.append(name)
    external_present={x.strip().upper() for x in args.external_present.split(",") if x.strip()};external_missing=[x for x in EXTERNAL_REQUIRED_LANES if x.upper() not in external_present]
    clean=not missing and not degraded and not external_missing;status="WORLD_COMPLETE" if clean else "PARTIAL_WORLD_COVERAGE"
    payload={"contract":"SOURCE_COVERAGE_GUARD_V10_PCS_DIRECT_RECONCILE_PROOF","discovery_mode":args.mode,"coverage_status":status,"worldwide_claim_allowed":clean,"expected_materialized_packs":len(expected_packs),"present_materialized_packs":len(expected_packs)-len(missing),"missing_packs":missing,"degraded_packs":degraded,"external_required_lanes":EXTERNAL_REQUIRED_LANES,"external_present_lanes":sorted(external_present),"external_missing_lanes":external_missing,"strict_exhaustion_sources":sorted(STRICT_EXHAUSTION_SOURCES),"pack_health":health,"semantics":"WORLD_COMPLETE means every configured live-candidate-capable lane materialized cleanly and every adapter with an exhaustion contract proved full traversal. PCS proof checks are contract-aware: legacy browser/direct-post collectors require Current Opportunity filter and stable-page proof; official bulk OCDS collectors require complete requested month x noticeType partitions including Website Contract Notice 101; and V4 reconciled packs additionally require a complete independent Current Opportunity traversal with every official current row exact-matched into the bulk. Archive-only lanes, source caps, runtime budgets, request failures or missing exhaustion proof keep coverage PARTIAL. This still does not mean every procurement authority on Earth is configured."}
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(payload,indent=2,ensure_ascii=False))
    if args.strict and not clean:raise SystemExit(3)
if __name__=="__main__":main()
