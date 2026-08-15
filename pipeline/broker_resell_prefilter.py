#!/usr/bin/env python3
from __future__ import annotations

"""High-precision broker/resell prefilter for live procurement discovery.

Separate from CORE_DIGITAL / SOLO_LEAN. Only manually QA-promoted motions:
  * Software licences / SaaS resale
  * Promotional merchandise

Fail-closed changes after first live scan QA:
* broker intent must be explicit in the procurement TITLE;
* pure-software lane rejects hardware/medical/physical-product title collisions;
* US SAM.gov non-bid stages, sole-source notices and restricted set-asides are
  excluded for this Belgium-based general-open broker motion;
* historical country priors are applied only after deterministic country resolution.

A high score means only "retrieve DCE and validate economics/channel constraints".
It never means eligible, profitable, or GREEN.
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

SOFTWARE_TITLE_PATTERNS = [
    r"software licen[cs](?:e|es|ing)", r"software subscription", r"software licensing",
    r"software licencing", r"licences? logicielles?", r"saas(?: subscription| licence| license| renewal)?",
    r"subscription renewal", r"software renewal", r"software subscriptions?",
]
PROMO_TITLE_PATTERNS = [
    r"promotional merchandise", r"branded merchandise", r"promotional items?",
    r"objets? publicitaires?", r"articles? promotionnels?", r"corporate gifts?",
    r"branded promotional", r"promotional products?",
]

SOFTWARE_NEG = [
    r"custom software development", r"application development", r"software development services",
    r"system integration", r"systems integration", r"implementation project", r"migration project",
    r"managed service", r"penetration test", r"cybersecurity services", r"consultancy-only",
]
PROMO_NEG = [
    r"full service marketing", r"event management services", r"campaign management services",
    r"advertising agency services", r"media buying",
]

# Pure-software resale should not be inferred from a licence line buried inside a
# physical system/device procurement. High precision is more valuable than recall.
SOFTWARE_TITLE_COLLISIONS = [
    r"medical", r"clinical", r"device", r"equipment", r"hardware", r"terminal", r"kiosk",
    r"rack system", r"irrigator", r"ventilat", r"oxygen generation", r"transmitter system",
    r"fire alarm", r"instrument", r"appliance", r"printer", r"server system", r"laptop", r"monitor",
    r"vehicle", r"scanner system", r"x[- ]ray", r"ultrasonic",
]
HARD_NEG = [
    r"construction works", r"civil works", r"building works", r"security clearance required",
    r"classified information",
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


def title_of(r):
    return norm(first(r, ["title", "name", "tender_title", "notice_title", "description_title"]))


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
    if u.startswith("US-SAM:"):return "US_SAM"
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
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if not d.tzinfo:d=d.replace(tzinfo=timezone.utc)
        return d>datetime.now(timezone.utc)
    except:return True


def us_open_market_ok(r, title: str) -> tuple[bool,str]:
    if "sole source" in title or "notice of intent" in title:
        return False,"US_SOLE_SOURCE_OR_INTENT"
    typ=norm(first(r,["type","notice_type","procurement_type"]))
    if any(x in typ for x in ["sources sought","special notice","presolicitation","justification","award notice","intent to sole"]):
        return False,"US_NON_BID_STAGE"
    sa=norm(first(r,["set_aside","setAside","set_aside_type","type_of_set_aside"]))
    if sa and sa not in {
        "none","n/a","na","not applicable","no set aside used","no set-aside used",
        "not set aside","unrestricted","full and open competition","false"
    }:
        return False,"US_RESTRICTED_SET_ASIDE"
    return True,""


def classify(r, priors):
    title=title_of(r); text=text_of(r)
    if not title or not text:return None
    if any(re.search(p,text,re.I) for p in HARD_NEG):return None
    c=cid(r); sf=source_family(r,c)
    if sf=="US_SAM":
        ok,why=us_open_market_ok(r,title)
        if not ok:return None

    candidates=[]

    spos=[p for p in SOFTWARE_TITLE_PATTERNS if re.search(p,title,re.I)]
    if spos and not any(re.search(p,title,re.I) for p in SOFTWARE_TITLE_COLLISIONS):
        sneg=[p for p in SOFTWARE_NEG if re.search(p,text,re.I)]
        score=48 + min(12,4*(len(spos)-1)) - 16*len(sneg)
        v=numeric_value(r)
        if v is not None and v>0:
            if 5_000<=v<=150_000:score+=16
            elif v<=400_000:score+=10
            elif v<=1_000_000:score+=2
            elif v>3_000_000:score-=18
        if re.search(r"framework|accord-cadre|rahmenvertrag|supply arrangement|qualification system",text,re.I):score-=5
        channel=bool(re.search(r"renewal|support|cisco|adobe|microsoft|splunk|palo alto|ibm|esri|autocad|nutanix|oracle|vmware",title,re.I))
        if channel:score-=4
        hd,hr=historical_adjustment(r,priors or {})
        score+=hd
        candidates.append((score,"Software licences / SaaS resale","BROKER_SOFTWARE_CHANNEL",spos,sneg,v,channel,hd,hr))

    ppos=[p for p in PROMO_TITLE_PATTERNS if re.search(p,title,re.I)]
    if ppos:
        pneg=[p for p in PROMO_NEG if re.search(p,text,re.I)]
        score=46 + min(12,4*(len(ppos)-1)) - 16*len(pneg)
        v=numeric_value(r)
        if v is not None and v>0:
            if 5_000<=v<=150_000:score+=16
            elif v<=400_000:score+=10
            elif v<=1_000_000:score+=2
            elif v>3_000_000:score-=18
        if re.search(r"framework|accord-cadre|rahmenvertrag|supply arrangement|qualification system",text,re.I):score-=5
        hd,hr=historical_adjustment(r,priors or {})
        score+=hd
        candidates.append((score,"Promotional merchandise","BROKER_PHYSICAL_GOODS",ppos,pneg,v,False,hd,hr))

    if not candidates:return None
    return max(candidates,key=lambda x:x[0])


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
            score,lane,motion,pos,neg,val,channel_risk,hist_delta,hist_reasons=x
            if score<42:continue
            title=first(r,["title","name","tender_title","notice_title"]);buyer=first(r,["buyer","buyer_name","authority","contracting_authority","organisation","organization"])
            sig=(norm(title),norm(buyer))
            if sig[0] and sig in dedupe:continue
            dedupe.add(sig)
            sf=source_family(r,c)
            ranked.append({
                "candidate_id":c,"broker_score":score,"broker_lane":lane,"commercial_motion":motion,
                "source_family":sf,"title":title,"buyer":buyer,"deadline":first(r,["deadline","submission_deadline","closing_date","close_date"]),
                "estimated_value":val,"channel_authorization_risk":channel_risk,
                "working_capital_risk":"CHECK_DCE_AND_PAYMENT_TERMS","positive_patterns":pos,"negative_patterns":neg,
                "historical_priority_adjustment":hist_delta,"historical_priority_reasons":hist_reasons,
                "semantic_basis":"TITLE_ANCHORED_MANUAL_QA_V2","decision":"DCE_ECONOMICS_REVIEW_ONLY"
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
        "commercial_motion":"BROKER_RESELL","semantic_policy":"TITLE_ANCHORED_MANUAL_QA_V2",
        "selection_reason":"Manually QA-promoted broker lanes only. DCE and supplier economics/channel validation required before any pursuit decision.",
        "candidate_ids":[x["candidate_id"] for x in selected]
    }
    Path(a.selection).write_text(json.dumps(manifest,ensure_ascii=False)+"\n",encoding="utf-8")
    summary={"source_run":a.run_id,"eligible":len(ranked),"saved_top":len(top),"selected":len(selected),"by_source":dict(counts),"by_lane":dict(lane_counts),"sample":selected[:40],"generated_at":datetime.now(timezone.utc).isoformat()}
    Path(a.out+".summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
