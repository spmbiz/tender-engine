#!/usr/bin/env python3
from __future__ import annotations

"""High-precision broker/resell prefilter for live procurement discovery.

This is intentionally separate from CORE_DIGITAL / SOLO_LEAN scoring. It targets
only manually QA-promoted broker motions:
  * Software licences / SaaS resale
  * Promotional merchandise

A high score means "worth retrieving the DCE and checking economics/channel
constraints". It never means eligible, profitable, or GREEN.
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from pipeline.historical_market_priors import load as load_historical_priors, adjustment as historical_adjustment
except ImportError:
    from historical_market_priors import load as load_historical_priors, adjustment as historical_adjustment

LANES = [
    {
        "name": "Software licences / SaaS resale",
        "patterns": [
            r"software licen[cs](?:e|es|ing)", r"software subscription", r"software licensing",
            r"software licencing", r"licences? logicielles?", r"saas subscription",
            r"subscription renewal", r"software renewal",
        ],
        "negatives": [
            r"custom software development", r"application development", r"software development services",
            r"system integration", r"systems integration", r"implementation project", r"migration project",
            r"managed service", r"penetration test", r"cybersecurity services", r"consultancy-only",
        ],
        "base": 48,
        "motion": "BROKER_SOFTWARE_CHANNEL",
    },
    {
        "name": "Promotional merchandise",
        "patterns": [
            r"promotional merchandise", r"branded merchandise", r"promotional items?",
            r"objets? publicitaires?", r"articles? promotionnels?", r"corporate gifts?",
            r"branded promotional", r"promotional products?",
        ],
        "negatives": [
            r"full service marketing", r"event management services", r"campaign management services",
            r"advertising agency services", r"media buying",
        ],
        "base": 46,
        "motion": "BROKER_PHYSICAL_GOODS",
    },
]

HARD_NEG = [
    r"construction works", r"civil works", r"building works", r"medical device", r"clinical services",
    r"laboratory equipment", r"security clearance required", r"classified information",
]


def norm(v):
    return re.sub(r"\s+", " ", str(v or "")).strip().casefold()


def first(r, keys):
    for k in keys:
        v = r.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def cid(r):
    return str(first(r, ["candidate_id", "id", "notice_id", "tender_id", "ocid", "reference", "identifier"]) or "").strip()


def text_of(r):
    vals=[]
    for k in ["title","name","tender_title","notice_title","description","summary","short_description","scope","object","procurement_description"]:
        v=r.get(k)
        if isinstance(v,str) and v.strip(): vals.append(v)
    return norm(" \n ".join(vals))


def numeric_value(r):
    for k in ["estimated_value","value","budget","amount","contract_value","value_amount"]:
        v=r.get(k)
        if isinstance(v,(int,float)): return float(v)
        if isinstance(v,str):
            m=re.search(r"\d[\d\s,.]*",v)
            if m:
                s=m.group(0).replace(" ","")
                if s.count(",")==1 and "." not in s: s=s.replace(",",".")
                else: s=s.replace(",","")
                try:return float(s)
                except:pass
    return None


def source_family(r,c):
    raw=norm(first(r,["portal","source","source_name","jurisdiction","country","country_code"])).upper()
    u=c.upper()
    if u.startswith("TED:"):return "TED"
    if u.startswith(("UK:","CF:")):return "UK"
    if u.startswith("FR:"):return "FR"
    if u.startswith("DE:"):return "DE"
    if u.startswith("CA:"):return "CA"
    if u.startswith("QC:"):return "QC"
    if u.startswith("IE:"):return "IE"
    if u.startswith("AU:"):return "AU"
    return raw[:30] or "OTHER"


def deadline_ok(r):
    v=first(r,["deadline","submission_deadline","closing_date","close_date","tender_deadline"])
    if not v:return True
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"));
        if not d.tzinfo:d=d.replace(tzinfo=timezone.utc)
        return d>datetime.now(timezone.utc)
    except:return True


def classify(r, priors):
    t=text_of(r)
    if not t:return None
    if any(re.search(p,t,re.I) for p in HARD_NEG):return None
    matches=[]
    for lane in LANES:
        pos=[p for p in lane["patterns"] if re.search(p,t,re.I)]
        if not pos:continue
        neg=[p for p in lane["negatives"] if re.search(p,t,re.I)]
        score=lane["base"] + min(12,4*(len(pos)-1)) - 14*len(neg)
        v=numeric_value(r)
        if v is not None and v>0:
            if 5_000<=v<=150_000:score+=16
            elif v<=400_000:score+=10
            elif v<=1_000_000:score+=2
            elif v>3_000_000:score-=18
        # Frameworks can be excellent but may imply admission/call-off burden.
        if re.search(r"framework|accord-cadre|rahmenvertrag|supply arrangement|qualification system",t,re.I):score-=5
        # SaaS renewals often require an authorised channel; do not reject, just mark risk.
        channel_risk = lane["name"].startswith("Software") and bool(re.search(r"renewal|support|cisco|adobe|microsoft|splunk|palo alto|ibm|esri|autocad|nutanix",t,re.I))
        if channel_risk:score-=4
        hist_delta,hist_reasons=historical_adjustment(r,priors or {})
        score+=hist_delta
        matches.append((score,lane,pos,neg,v,channel_risk,hist_delta,hist_reasons))
    if not matches:return None
    return max(matches,key=lambda x:x[0])


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True);ap.add_argument("--out",required=True);ap.add_argument("--selection",required=True)
    ap.add_argument("--run-id",type=int,required=True);ap.add_argument("--top",type=int,default=300);ap.add_argument("--select",type=int,default=100);ap.add_argument("--max-per-source",type=int,default=25)
    a=ap.parse_args();priors=load_historical_priors();ranked=[];dedupe=set()
    with open(a.input,encoding="utf-8",errors="replace") as f:
        for line in f:
            if not line.strip():continue
            try:r=json.loads(line)
            except:continue
            c=cid(r)
            if not c or not deadline_ok(r):continue
            x=classify(r,priors)
            if not x:continue
            score,lane,pos,neg,val,channel_risk,hist_delta,hist_reasons=x
            if score<42:continue
            title=first(r,["title","name","tender_title","notice_title"]);buyer=first(r,["buyer","buyer_name","authority","contracting_authority","organisation","organization"])
            sig=(norm(title),norm(buyer))
            if sig[0] and sig in dedupe:continue
            dedupe.add(sig)
            sf=source_family(r,c)
            ranked.append({
                "candidate_id":c,"broker_score":score,"broker_lane":lane["name"],"commercial_motion":lane["motion"],
                "source_family":sf,"title":title,"buyer":buyer,"deadline":first(r,["deadline","submission_deadline","closing_date","close_date"]),
                "estimated_value":val,"channel_authorization_risk":channel_risk,
                "working_capital_risk":"CHECK_DCE_AND_PAYMENT_TERMS","positive_patterns":pos,"negative_patterns":neg,
                "historical_priority_adjustment":hist_delta,"historical_priority_reasons":hist_reasons,
                "decision":"DCE_ECONOMICS_REVIEW_ONLY"
            })
    ranked.sort(key=lambda x:(x["broker_score"],-(x.get("estimated_value") or 10**18)),reverse=True)
    top=ranked[:a.top];Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    with open(a.out,"w",encoding="utf-8") as f:
        for x in top:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    selected=[];counts=Counter();lane_counts=Counter()
    for x in top:
        if counts[x["source_family"]]>=a.max_per_source:continue
        selected.append(x);counts[x["source_family"]]+=1;lane_counts[x["broker_lane"]]+=1
        if len(selected)>=a.select:break
    manifest={
        "wide_read_run_id":a.run_id,"default_preliminary_score":78,"status":"DCE_PENDING",
        "commercial_motion":"BROKER_RESELL","selection_reason":"Manually QA-promoted broker lanes only. DCE and supplier economics/channel validation required before any pursuit decision.",
        "candidate_ids":[x["candidate_id"] for x in selected]
    }
    Path(a.selection).write_text(json.dumps(manifest,ensure_ascii=False)+"\n",encoding="utf-8")
    summary={"source_run":a.run_id,"eligible":len(ranked),"saved_top":len(top),"selected":len(selected),"by_source":dict(counts),"by_lane":dict(lane_counts),"sample":selected[:40],"generated_at":datetime.now(timezone.utc).isoformat()}
    Path(a.out+".summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
