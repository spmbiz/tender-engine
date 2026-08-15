#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# This is a retrieval prior, never an eligibility verdict.  It intentionally
# favors small fixed deliverables and commodity fulfilment, and penalizes the
# institutional patterns that failed the first two SOLO proof runs.
STRONG = [
    (34,["printing","print services","digital printing","impression","druck","brochure","leaflet","flyer","booklet"]),
    (34,["translation","traduction","übersetzung","transcription","subtitling","captioning"]),
    (32,["website design","web design","website redesign","site web","site internet","wordpress","small website"]),
    (30,["graphic design","design graphique","layout","mise en page","typesetting","illustration","infographic"]),
    (28,["video editing","post-production","post production","photography","photo services","motion graphics"]),
    (27,["digitisation","digitization","document scanning","document imaging","data entry","records scanning"]),
    (24,["promotional material","promotional items","merchandise","signage supply"]),
    (22,["hard drive","hard disk","monitor supply","laptop supply","computer equipment","office equipment"]),
    (20,["copywriting","proofreading","editing services","content writing"]),
]
BONUS = [
    (22,["request for quotation","request for quote","rfq","quotation","quote request"]),
    (18,["below threshold","below-threshold","low value","small purchase","simplified procedure"]),
    (12,["single lot","one-off","one off","fixed price"]),
    (8,["remote","online delivery","electronic delivery"]),
]
PENALTY = [
    (55,["framework agreement","framework contract","dynamic purchasing system","dps ","multi-supplier framework"]),
    (50,["managed service","managed services","service desk","24/7","24x7","soc service","security operations"]),
    (45,["system integration","systems integration","enterprise architecture","erp","sap ","oracle ","data centre","data center","network infrastructure","cybersecurity","cyber security"]),
    (42,["authorized reseller","authorised reseller","manufacturer authorization","manufacturer authorisation","gold partner","certified partner"]),
    (40,["turnover requirement","minimum turnover","annual turnover","financial standing"]),
    (38,["minimum of 3 references","three references","3 references","similar contracts","similar projects","previous experience"]),
    (34,["key personnel","project manager 7","senior consultant","team cv","curriculum vitae","professional indemnity"]),
    (32,["maintenance and support","hosting and maintenance","support and maintenance","multi-year","multi year"]),
    (28,["consultancy","consulting services","strategy services","communications agency","full service agency"]),
    (24,["implementation services","migration services","integration services","development framework"]),
    (22,["event management","construction","installation works","civil works","medical","pharmaceutical"]),
]


def flatten(obj):
    out=[]
    if isinstance(obj,dict):
        for v in obj.values(): out.extend(flatten(v))
    elif isinstance(obj,list):
        for v in obj: out.extend(flatten(v))
    elif isinstance(obj,(str,int,float)): out.append(str(obj))
    return out


def first(r,keys):
    for k in keys:
        v=r.get(k)
        if v not in (None,"",[],{}): return v
    return None


def cid(r):
    return str(first(r,["candidate_id","id","notice_id","tender_id","ocid","reference","identifier"]) or "").strip()


def value(r):
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


def source(r,c):
    s=str(first(r,["portal","source","source_name","jurisdiction","country","country_code"]) or "").upper()
    u=c.upper()
    if u.startswith("TED:"): return "TED"
    if u.startswith("IE:"): return "IE"
    if u.startswith("UK:") or u.startswith("CF:") or "CONTRACTS FINDER" in s:return "UK"
    if u.startswith("FR:") or "BOAMP" in s:return "FR"
    if u.startswith("DE") or "DOE" in s:return "DE"
    if u.startswith("CA:") or "CANADABUYS" in s:return "CA"
    if u.startswith("QC:") or "SEAO" in s:return "QC"
    if u.startswith("NZ:") or "GETS" in s:return "NZ"
    if u.startswith("AU:") or "AUSTENDER" in s:return "AU"
    if u.startswith("LU-"):return "LU"
    if u.startswith("PL-"):return "PL"
    return s[:28] or "OTHER"


def deadline_ok(r):
    v=first(r,["deadline","submission_deadline","closing_date","close_date","tender_deadline"])
    if not v:return True
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d > datetime.now(timezone.utc)
    except:return True


def score(r):
    text=" \n ".join(flatten(r)).casefold()
    pts=0; pos=[]; neg=[]
    for w,terms in STRONG:
        f=[t for t in terms if t in text]
        if f: pts+=w+min(8,2*(len(f)-1)); pos.extend(f[:3])
    for w,terms in BONUS:
        f=[t for t in terms if t in text]
        if f: pts+=w; pos.extend(f[:2])
    for w,terms in PENALTY:
        f=[t for t in terms if t in text]
        if f: pts-=w; neg.extend(f[:3])
    v=value(r)
    if v is not None and v>0:
        if v<=25_000: pts+=30; pos.append("value<=25k")
        elif v<=50_000: pts+=24; pos.append("value<=50k")
        elif v<=100_000: pts+=14; pos.append("value<=100k")
        elif v<=150_000: pts+=5
        elif v<=250_000: pts-=12; neg.append("value>150k")
        elif v<=500_000: pts-=28; neg.append("value>250k")
        else: pts-=45; neg.append("value>500k")
    # Directly prefer simple national/local procurement over TED-sized institutional calls.
    sf=source(r,cid(r))
    if sf in {"UK","FR","DE","CA","QC","NZ","AU","LU"}: pts+=8
    if sf=="TED": pts-=8
    if sf=="PL": pts-=30  # proof lane deliberately seeks geographic breadth.
    if r.get("seen_before") is True: pts-=40
    return pts,sorted(set(pos)),sorted(set(neg)),v,sf


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True); ap.add_argument("--out",required=True)
    ap.add_argument("--selection",required=True); ap.add_argument("--run-id",type=int,required=True)
    ap.add_argument("--top",type=int,default=500); ap.add_argument("--select",type=int,default=80)
    ap.add_argument("--max-per-source",type=int,default=12)
    a=ap.parse_args()
    ranked=[]
    for line in open(a.input,encoding="utf-8",errors="replace"):
        if not line.strip():continue
        try:r=json.loads(line)
        except:continue
        c=cid(r)
        if not c or not deadline_ok(r):continue
        s,p,n,v,sf=score(r)
        if s<20:continue
        ranked.append({"candidate_id":c,"solo_lean_prior":s,"source_family":sf,
            "title":first(r,["title","name","tender_title","notice_title"]),
            "buyer":first(r,["buyer","buyer_name","authority","contracting_authority","organisation","organization"]),
            "deadline":first(r,["deadline","submission_deadline","closing_date","close_date"]),
            "estimated_value":v,"positive_hits":p,"risk_hits":n})
    ranked.sort(key=lambda x:(x["solo_lean_prior"],-(x.get("estimated_value") or 10**18)),reverse=True)
    top=ranked[:a.top]
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    with open(a.out,"w",encoding="utf-8") as f:
        for x in top:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    selected=[]; counts=Counter()
    for x in top:
        sf=x["source_family"]
        if counts[sf]>=a.max_per_source:continue
        selected.append(x); counts[sf]+=1
        if len(selected)>=a.select:break
    manifest={"wide_read_run_id":a.run_id,"default_preliminary_score":80,"status":"DCE_PENDING",
      "selection_reason":"SOLO_LEAN proof prefilter only: low qualification-burden prior; substantive DCE and every mandatory gate required. Partnerable/borrowed capacity is forbidden.",
      "candidate_ids":[x["candidate_id"] for x in selected]}
    Path(a.selection).write_text(json.dumps(manifest,ensure_ascii=False)+"\n",encoding="utf-8")
    summary={"source_run":a.run_id,"eligible":len(ranked),"selected":len(selected),"by_source":dict(counts),
      "top_sample":selected[:25],"generated_at":datetime.now(timezone.utc).isoformat()}
    Path(a.out+".summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
