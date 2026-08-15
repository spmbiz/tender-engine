#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Retrieval prior only. Final SOLO requires substantive DCE + every mandatory gate.
STRONG = [
    (40,["digital printing","print services","printing services","impression","imprimerie","druckleistung","brochure","leaflet","flyer","booklet"]),
    (40,["translation services","translation","traduction","übersetzungsleistung","transcription","subtitling","captioning"]),
    (38,["website design","web design","website redesign","site web","site internet","wordpress website","webseite"]),
    (36,["graphic design","design graphique","layout services","mise en page","typesetting","illustration","infographic"]),
    (34,["video editing","post-production","post production","photography services","photo services","motion graphics"]),
    (34,["document digitisation","document digitization","document scanning","document imaging","data entry","records scanning"]),
    (30,["promotional material","promotional items","merchandise","signage supply"]),
    (28,["hard drive","hard disk","monitor supply","laptop supply","computer equipment","office equipment"]),
    (25,["copywriting","proofreading","editing services","content writing"]),
]
BONUS = [
    (28,["request for quotation","request for quote","rfq","quote request"]),
    (24,["below threshold","below-threshold","low value","small purchase","simplified procedure"]),
    (14,["one-off","one off","fixed price","single delivery"]),
    (8,["remote delivery","electronic delivery","online delivery"]),
]
PENALTY = [
    (100,["notice of intent to sole source","sole source","single source","oem technical training"]),
    (65,["framework agreement","framework contract","dynamic purchasing system","multi-supplier framework","bpa "]),
    (58,["managed service","managed services","service desk","24/7","24x7","security operations"]),
    (52,["system integration","systems integration","enterprise architecture","erp implementation","sap implementation","oracle implementation","data centre","data center","network infrastructure","cybersecurity","cyber security"]),
    (48,["authorized reseller","authorised reseller","manufacturer authorization","manufacturer authorisation","gold partner","certified partner"]),
    (46,["minimum turnover","annual turnover","financial standing"]),
    (44,["three references","3 references","similar contracts","similar projects","previous experience"]),
    (40,["key personnel","senior consultant","curriculum vitae","professional indemnity"]),
    (38,["maintenance and support","hosting and maintenance","support and maintenance","multi-year","multi year"]),
    (35,["consultancy","consulting services","strategy services","communications agency","full service agency"]),
    (30,["implementation services","migration services","integration services"]),
    (60,["construction","installation works","civil works","hvac","sanitary installations","heating installations","motor control panel"]),
    (50,["medical","pharmaceutical","clinical","laboratory equipment"]),
]


def first(r,keys):
    for k in keys:
        v=r.get(k)
        if v not in (None,"",[],{}): return v
    return None


def norm(v): return re.sub(r"\s+"," ",str(v or "")).strip().casefold()

def cid(r): return str(first(r,["candidate_id","id","notice_id","tender_id","ocid","reference","identifier"]) or "").strip()

def business_text(r):
    vals=[]
    for k in ["title","name","tender_title","notice_title","description","summary","short_description","scope","object","procurement_description"]:
        v=r.get(k)
        if isinstance(v,str) and v.strip(): vals.append(v)
    return norm(" \n ".join(vals))

def value(r):
    for k in ["estimated_value","value","budget","amount","contract_value","value_amount"]:
        v=r.get(k)
        if isinstance(v,(int,float)): return float(v)
        if isinstance(v,str):
            m=re.search(r"\d[\d\s,.]*",v)
            if m:
                s=m.group(0).replace(" ","")
                if s.count(",")==1 and "." not in s:s=s.replace(",",".")
                else:s=s.replace(",","")
                try:return float(s)
                except:pass
    return None

def source(r,c):
    s=norm(first(r,["portal","source","source_name","jurisdiction","country","country_code"])).upper(); u=c.upper()
    if u.startswith("TED:"):return "TED"
    if u.startswith("IE:"):return "IE"
    if u.startswith(("UK:","CF:")) or "CONTRACTS FINDER" in s:return "UK"
    if u.startswith("FR:") or "BOAMP" in s:return "FR"
    if u.startswith("DE") or "DOE" in s:return "DE"
    if u.startswith("CA:") or "CANADABUYS" in s:return "CA"
    if u.startswith("QC:") or "SEAO" in s:return "QC"
    if u.startswith("NZ:") or "GETS" in s:return "NZ"
    if u.startswith("AU:") or "AUSTENDER" in s:return "AU"
    if u.startswith("LU-"):return "LU"
    if u.startswith("PL-"):return "PL"
    if u.startswith("US-SAM:"):return "US_SAM"
    return s[:28] or "OTHER"

def deadline_ok(r):
    v=first(r,["deadline","submission_deadline","closing_date","close_date","tender_deadline"])
    if not v:return True
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00")); d=d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return d>datetime.now(timezone.utc)
    except:return True

def score(r):
    text=business_text(r); c=cid(r); sf=source(r,c); pts=0; pos=[]; neg=[]
    if not text:return -999,[],[],None,sf
    for w,terms in STRONG:
        f=[t for t in terms if t in text]
        if f:pts+=w+min(8,2*(len(f)-1));pos.extend(f[:3])
    for w,terms in BONUS:
        f=[t for t in terms if t in text]
        if f:pts+=w;pos.extend(f[:2])
    for w,terms in PENALTY:
        f=[t for t in terms if t in text]
        if f:pts-=w;neg.extend(f[:3])
    v=value(r)
    if v is not None and v>0:
        if v<=25_000:pts+=34;pos.append("value<=25k")
        elif v<=50_000:pts+=28;pos.append("value<=50k")
        elif v<=100_000:pts+=18;pos.append("value<=100k")
        elif v<=150_000:pts+=6
        elif v<=250_000:pts-=16;neg.append("value>150k")
        elif v<=500_000:pts-=32;neg.append("value>250k")
        else:pts-=50;neg.append("value>500k")
    if sf in {"UK","FR","DE","CA","QC","NZ","AU","LU"}:pts+=10
    if sf=="TED":pts-=12
    if sf=="PL":pts-=40
    if sf=="US_SAM":
        nt=norm(r.get("type")); sa=norm(r.get("set_aside"))
        if any(x in nt for x in ["sources sought","special notice","presolicitation","justification","award"]):pts-=80;neg.append("sam-non-live-bid")
        if sa and sa not in {"none","n/a","na","not applicable","no set aside used","no set-aside used","not set aside","unrestricted","full and open competition"}:pts-=100;neg.append("sam-set-aside")
    if r.get("seen_before") is True:pts-=50
    return pts,sorted(set(pos)),sorted(set(neg)),v,sf

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True);ap.add_argument("--out",required=True);ap.add_argument("--selection",required=True);ap.add_argument("--run-id",type=int,required=True);ap.add_argument("--top",type=int,default=500);ap.add_argument("--select",type=int,default=80);ap.add_argument("--max-per-source",type=int,default=12);a=ap.parse_args()
    ranked=[]; seen_tb=set()
    for line in open(a.input,encoding="utf-8",errors="replace"):
        if not line.strip():continue
        try:r=json.loads(line)
        except:continue
        c=cid(r)
        if not c or not deadline_ok(r):continue
        title=first(r,["title","name","tender_title","notice_title"]);buyer=first(r,["buyer","buyer_name","authority","contracting_authority","organisation","organization"])
        tb=(norm(title),norm(buyer))
        if tb[0] and tb in seen_tb:continue
        s,p,n,v,sf=score(r)
        if s<25:continue
        seen_tb.add(tb)
        ranked.append({"candidate_id":c,"solo_lean_prior":s,"source_family":sf,"title":title,"buyer":buyer,"deadline":first(r,["deadline","submission_deadline","closing_date","close_date"]),"estimated_value":v,"positive_hits":p,"risk_hits":n})
    ranked.sort(key=lambda x:(x["solo_lean_prior"],-(x.get("estimated_value") or 10**18)),reverse=True);top=ranked[:a.top]
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    with open(a.out,"w",encoding="utf-8") as f:
        for x in top:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    selected=[];counts=Counter()
    for x in top:
        sf=x["source_family"]
        if counts[sf]>=a.max_per_source:continue
        selected.append(x);counts[sf]+=1
        if len(selected)>=a.select:break
    manifest={"wide_read_run_id":a.run_id,"default_preliminary_score":80,"status":"DCE_PENDING","selection_reason":"SOLO_LEAN proof prefilter only. Final requires substantive DCE and every mandatory gate; partnerable/borrowed capacity forbidden.","candidate_ids":[x["candidate_id"] for x in selected]}
    Path(a.selection).write_text(json.dumps(manifest,ensure_ascii=False)+"\n",encoding="utf-8")
    summary={"source_run":a.run_id,"eligible":len(ranked),"selected":len(selected),"by_source":dict(counts),"top_sample":selected[:30],"generated_at":datetime.now(timezone.utc).isoformat()}
    Path(a.out+".summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
