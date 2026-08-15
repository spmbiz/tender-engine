#!/usr/bin/env python3
from __future__ import annotations

"""Build an exhaustive, non-destructive SPM live review pool.

Every snapshot row is preserved in exactly one review lane:
- PLAYBOOK_OR_LEAN_HIT: historical prior and/or broad lean-ontology evidence.
- RESIDUAL_OPEN_WORLD: everything else, still packeted for later GPT review.

The ranking is a review-order heuristic only. It cannot establish eligibility,
win probability, GREEN status, or any mandatory DCE gate.
"""

import argparse
import gzip
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from historical_market_priors import adjustment as historical_adjustment
from historical_market_priors import load as load_historical_priors

SOURCE_COUNTRY = {
    "US_SAM":"USA", "FR":"FRANCE", "DE":"GERMANY", "CA":"CANADA", "QC":"CANADA - QUEBEC",
    "UK":"UNITED KINGDOM", "IE":"IRELAND", "AU":"AUSTRALIA", "NZ":"NEW ZEALAND", "NL":"NETHERLANDS",
    "PL":"POLAND", "DK":"DENMARK", "FI":"FINLAND", "ES_PLACSP":"SPAIN", "GR_KHMDHS":"GREECE",
    "PT_BASE_OPEN":"PORTUGAL", "CZ_ZAKAZKY_GOV":"CZECHIA", "CH_SIMAP":"SWITZERLAND", "NO_DOFFIN":"NORWAY",
    "LV_IUB":"LATVIA", "LU":"LUXEMBOURG", "BE":"BELGIUM", "CY":"CYPRUS", "MT":"MALTA",
}

# Broad enough to surface lean work outside the current historical top-11.
LEAN_PATTERNS = {
    "web_cms": r"website|web site|site web|site internet|webseite|internetauftritt|wordpress|drupal|\bcms\b|web portal|portail web|webportal",
    "design_dtp": r"graphic design|design graphique|conception graphique|graphisme|mise en page|desktop publishing|\bdtp\b|visual identity|identit[eé] visuelle|infograph",
    "print_broker": r"printing services?|prestations? d['’]impression|services? d['’]impression|travaux d['’]impression|imprimerie|print production|brochure|magazine printing|routage|mailing|mise sous pli",
    "promo_goods": r"promotional merchandise|branded merchandise|promotional items|objets publicitaires|articles promotionnels|goodies|corporate gifts",
    "translation": r"translation services?|professional translation|technical translation|traduction de textes|prestations? de traduction|services? de traduction|linguistic services?",
    "transcription": r"transcription services?|retranscription|speech[- ]to[- ]text|meeting transcription|debate transcription|st[eé]notyp",
    "digitization": r"document digitization|document digitisation|num[eé]risation de documents|digitalisation de documents|document scanning|\bocr\b|archive digitization|archive digitisation",
    "video_media": r"video production|film production|production vid[eé]o|motion graphics|animation video|audiovisual production|podcast production|content production",
    "social_marketing": r"social media management|community management|gestion des r[eé]seaux sociaux|digital marketing|seo services?|search engine optimization|content marketing",
    "research_surveys": r"market research|customer survey|satisfaction survey|opinion poll|research panel|user research",
    "media_monitoring": r"media monitoring|press monitoring|social listening|revue de presse|veille m[eé]diatique",
    "software_resale": r"software licen[cs](?:e|es|ing)|software subscription|saas subscription|licences? logicielles?|license renewal|licence renewal",
    "automation_data": r"robotic process automation|\brpa\b|workflow automation|process automation|data entry|data processing|document processing|low[- ]code|no[- ]code|chatbot|artificial intelligence|\bai\b services?",
    "accessibility": r"web accessibility|digital accessibility|accessibilit[eé] num[eé]rique|\bwcag\b|\brgaa\b|pdf[- ]ua",
    "hosting_support": r"web hosting|website maintenance|web maintenance|hosting and support|h[eé]bergement.*site|maintenance.*site (?:web|internet)|pflege.*webseite|wartung.*webseite",
}
LEAN_RX = {k:re.compile(v,re.I) for k,v in LEAN_PATTERNS.items()}

# Review flags, never silent exclusions.
BLOCKER_PATTERNS = {
    "SOLE_SOURCE_OR_OEM": r"sole source|only one responsible source|source approval request|approved source|original equipment manufacturer|\boem\b|single source",
    "MANDATORY_ONSITE_OR_FIELD": r"must be performed on[- ]site|required on[- ]site|work will be performed on[- ]site|mandatory site visit|présence sur site obligatoire|intervention sur site|vor ort",
    "REGULATED_OR_CERTIFIED_STAFF": r"mandatory qualifications|must be certified|required certification|licensed professional|professional license|security clearance|habilitat|certifi[eé].{0,50}obligatoire",
    "SET_ASIDE_OR_LOCAL_RESTRICTION": r"small business set[- ]aside|8\(a\)|hubzone|service[- ]disabled veteran|woman[- ]owned small business|local suppliers? only|domestic suppliers? only",
    "SOURCES_SOUGHT_OR_RFI": r"sources sought|request for information|\brfi\b|market research purposes|information and planning purposes|not a request for (?:proposal|quotation|bid)",
    "CONSTRUCTION_HEAVY": r"construction works?|civil works?|general contractor|architectural and engineering|road works?|building works?|ma[iî]trise d['’]oeuvre|travaux de construction",
    "MEDICAL_CLINICAL": r"clinical services?|medical services?|patient care|physician|nursing services?|hospital staffing|medical simulator operator",
}
BLOCKER_RX={k:re.compile(v,re.I|re.S) for k,v in BLOCKER_PATTERNS.items()}


def text(rec:dict[str,Any])->str:
    return " ".join(str(rec.get(k) or "") for k in ("title","description","cpv_or_category","notice_eligibility","procedure")).strip()


def infer_country(rec:dict[str,Any])->str:
    c=str(rec.get("country") or "").strip().upper()
    if c and c!="UNKNOWN": return c
    return SOURCE_COUNTRY.get(str(rec.get("source_family") or "").upper(), "")


def val_number(v:Any)->float|None:
    if isinstance(v,(int,float)) and not isinstance(v,bool):
        return float(v) if math.isfinite(float(v)) else None
    if isinstance(v,str):
        s=v.strip().replace("\u00a0","").replace(" ","")
        m=re.search(r"-?\d+(?:[.,]\d+)?",s)
        if m:
            try:return float(m.group(0).replace(",","."))
            except Exception:return None
    return None


def row_analysis(rec:dict[str,Any], priors:dict)->dict:
    rec=dict(rec)
    country=infer_country(rec)
    if country and not rec.get("country"): rec["country"]=country
    t=text(rec)
    hist_delta,hist_reasons=historical_adjustment(rec,priors)
    lean=[k for k,rx in LEAN_RX.items() if rx.search(t)]
    blockers=[k for k,rx in BLOCKER_RX.items() if rx.search(t)]

    # Review order, not a tender score. Historical priors are capped and broad
    # ontology contributes only enough to surface candidates for GPT reading.
    review=20.0
    review += max(0,hist_delta)*5.0
    review += min(24.0, 8.0*len(lean))
    if rec.get("open_state")=="OPEN_CONFIRMED_BY_DEADLINE": review += 6
    if rec.get("description") and len(str(rec.get("description")))>250: review += 4
    if rec.get("notice_eligibility"): review += 2
    if rec.get("estimated_value") not in (None,""): review += 2
    # Flags lower review priority but never remove the row.
    review -= min(35.0, 9.0*len(blockers))
    review=max(0.0,min(89.0,review))

    bucket="PLAYBOOK_OR_LEAN_HIT" if hist_delta>0 or lean else "RESIDUAL_OPEN_WORLD"
    return {
        **rec,
        "resolved_country": country or None,
        "review_bucket": bucket,
        "review_priority": round(review,2),
        "historical_priority_adjustment": hist_delta,
        "historical_prior_reasons": hist_reasons,
        "lean_ontology_hits": lean,
        "pre_dce_blocker_flags": blockers,
        "review_rule":"Ordering heuristic only. GPT semantic review + authoritative DCE decide business fit; blockers are flags, not automatic final verdicts.",
    }


def write_jsonl(path:Path,rows):
    with path.open("w",encoding="utf-8") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot",required=True)
    ap.add_argument("--priors",default="control/historical_market_priors.json")
    ap.add_argument("--manifest",required=True)
    ap.add_argument("--coverage",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--packet-size",type=int,default=400)
    a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); (out/"residual-packets").mkdir(exist_ok=True)
    priors=load_historical_priors(a.priors)
    opener=gzip.open if str(a.snapshot).endswith(".gz") else open
    rows=[]
    with opener(a.snapshot,"rt",encoding="utf-8",errors="replace") as f:
        for line in f:
            if not line.strip():continue
            x=json.loads(line)
            if isinstance(x,dict):rows.append(row_analysis(x,priors))
    hits=[r for r in rows if r["review_bucket"]=="PLAYBOOK_OR_LEAN_HIT"]
    residual=[r for r in rows if r["review_bucket"]=="RESIDUAL_OPEN_WORLD"]
    hits.sort(key=lambda r:(-float(r["review_priority"]),r.get("deadline_utc") or "9999",r.get("candidate_id") or ""))
    residual.sort(key=lambda r:(r.get("deadline_utc") or "9999",r.get("source_family") or "",r.get("candidate_id") or ""))
    write_jsonl(out/"playbook_lean_hits.jsonl",hits)
    write_jsonl(out/"top_review_1000.jsonl",hits[:1000])
    packet_names=[]
    n=max(1,a.packet_size)
    for i in range(0,len(residual),n):
        name=f"residual-{i//n:04d}.jsonl"; packet_names.append(name); write_jsonl(out/"residual-packets"/name,residual[i:i+n])
    coverage=json.load(open(a.coverage,encoding="utf-8")); manifest=json.load(open(a.manifest,encoding="utf-8"))
    summary={
        "contract":"LIVE_SPM_REVIEW_POOL_V1","source_discovery_run":manifest.get("source_discovery_run"),
        "snapshot_rows":len(rows),"playbook_or_lean_hits":len(hits),"residual_open_world":len(residual),
        "coverage_status":coverage.get("coverage_status") or manifest.get("discovery_coverage_status"),
        "missing_packs":coverage.get("missing_packs") or [],"degraded_packs":coverage.get("degraded_packs") or [],
        "external_missing_lanes":coverage.get("external_missing_lanes") or [],
        "hit_ontology_counts":dict(Counter(x for r in hits for x in r["lean_ontology_hits"])),
        "hit_source_counts":dict(Counter(str(r.get("source_family") or "UNKNOWN") for r in hits).most_common()),
        "blocker_flag_counts":dict(Counter(x for r in rows for x in r["pre_dce_blocker_flags"])),
        "residual_packet_count":len(packet_names),"residual_packet_size":n,"residual_packet_files":packet_names,
        "preservation_rule":"Every snapshot row is represented in hit or residual output. Residuals are not discarded; they remain open-world review material.",
        "final_verdict_allowed":False,
    }
    assert len(hits)+len(residual)==len(rows)
    (out/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=="__main__":main()
