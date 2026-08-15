#!/usr/bin/env python3
import argparse, json, re
from pathlib import Path
from datetime import datetime, timezone

POSITIVE = [
    (22, ["website", "web site", "webdesign", "web design", "web development", "site web", "site internet", "internetseite", "webseite", "wordpress", "drupal", "cms", "content management system", "digital portal", "web portal", "online portal"]),
    (18, ["graphic design", "design graphique", "grafikdesign", "visual identity", "branding", "brand identity", "creative services", "communication design", "layout design"]),
    (17, ["video production", "video editing", "post production", "post-production", "animation", "motion graphics", "audiovisual", "film production", "editing services"]),
    (16, ["transcription", "captioning", "subtitling", "translation services", "traduction", "übersetzung", "localisation services"]),
    (15, ["printing", "print services", "impression", "druckleistungen", "brochure", "leaflet", "flyer", "booklet", "promotional material", "promotional items", "signage supply"]),
    (13, ["social media", "content creation", "digital content", "copywriting", "content production", "communications campaign", "marketing campaign"]),
    (12, ["e-learning", "elearning", "learning platform", "lms", "training content", "online training", "digital learning", "course development"]),
    (10, ["photography", "photo services", "illustration", "infographic", "presentation design"]),
    (8, ["survey design", "data entry", "document digitisation", "document digitization", "scanning services", "records digitisation"]),
]

NEGATIVE = [
    (35, ["construction works", "civil engineering", "roadworks", "bridge construction", "wastewater", "sewer", "asbestos", "roof replacement", "mechanical works", "electrical works", "hvac", "building works"]),
    (30, ["medical device", "pharmaceutical", "laboratory equipment", "surgical", "clinical", "ambulance", "radiology"]),
    (28, ["sap implementation", "oracle implementation", "erp implementation", "enterprise resource planning", "core banking", "scada", "industrial control"]),
    (25, ["cyber security operations", "soc service", "penetration testing", "network infrastructure", "data centre", "data center", "server hardware", "switches and routers", "firewall appliances"]),
    (22, ["architectural services", "structural engineering", "geotechnical", "quantity surveying", "environmental impact assessment"]),
    (18, ["fleet vehicles", "vehicle maintenance", "fuel supply", "catering services", "cleaning services", "security guarding", "waste collection"]),
]

BONUS = [
    (8, ["small business", "sme", "microenterprise", "lot", "framework lot"]),
    (7, ["remote", "online", "digital", "cloud hosted"]),
    (6, ["design and build", "maintenance and support", "hosting and maintenance"]),
]


def flatten_strings(obj):
    out=[]
    if isinstance(obj, dict):
        for v in obj.values(): out.extend(flatten_strings(v))
    elif isinstance(obj, list):
        for v in obj: out.extend(flatten_strings(v))
    elif isinstance(obj, (str,int,float)):
        out.append(str(obj))
    return out


def first(rec, keys):
    for k in keys:
        v=rec.get(k)
        if v not in (None, "", [], {}): return v
    return None


def candidate_id(rec):
    return str(first(rec,["candidate_id","id","notice_id","tender_id","ocid","reference","identifier"]) or "")


def source_family(rec, cid):
    s=str(first(rec,["source","source_name","portal","jurisdiction","country","country_code"]) or "").upper()
    c=cid.upper()
    if c.startswith("TED:"): return "TED"
    if c.startswith("IE:"): return "IE"
    if "CANADABUYS" in s or c.startswith("CA:"): return "CA"
    if "SEAO" in s or c.startswith("QC:"): return "QC"
    if "AUSTENDER" in s or c.startswith("AU:"): return "AU"
    if "GETS" in s or c.startswith("NZ:"): return "NZ"
    if "BOAMP" in s or c.startswith("FR:"): return "FR"
    if "DOE" in s or c.startswith("DE:"): return "DE"
    if "CONTRACTS FINDER" in s or c.startswith("UK:") or c.startswith("CF:"): return "UK"
    return s[:24] or "OTHER"


def numeric_value(rec):
    for k in ["estimated_value","value","budget","amount","contract_value","value_amount"]:
        v=rec.get(k)
        if isinstance(v,(int,float)): return float(v)
        if isinstance(v,str):
            nums=re.findall(r"\d[\d\s,.]*", v)
            if nums:
                x=nums[0].replace(" ","").replace(",","")
                try:return float(x)
                except: pass
    return None


def score_record(rec):
    text=" \n ".join(flatten_strings(rec)).lower()
    score=0; hits=[]; neg=[]
    for w, terms in POSITIVE:
        found=[t for t in terms if t in text]
        if found:
            score += w + min(8, 2*(len(found)-1)); hits.extend(found[:4])
    for w, terms in BONUS:
        found=[t for t in terms if t in text]
        if found: score += w; hits.extend(found[:2])
    for w, terms in NEGATIVE:
        found=[t for t in terms if t in text]
        if found: score -= w; neg.extend(found[:3])
    val=numeric_value(rec)
    if val is not None:
        if 15000 <= val <= 500000: score += 10
        elif 500000 < val <= 1000000: score += 3
        elif val > 3000000: score -= 12
    seen=first(rec,["seen_before","previously_seen","seen"])
    if seen is True or str(seen).lower()=="true": score -= 18
    # Keep specialist IT from dominating merely because it says portal/cloud.
    if any(x in text for x in ["software licences","software licenses","license renewal","licence renewal","managed service provider"]): score -= 10
    return score, sorted(set(hits)), sorted(set(neg)), val


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--top", type=int, default=1600)
    ap.add_argument("--select", type=int, default=320)
    ap.add_argument("--run-id", type=int, required=True)
    args=ap.parse_args()

    rows=[]
    with open(args.input,"r",encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try: rec=json.loads(line)
            except: continue
            cid=candidate_id(rec)
            if not cid: continue
            score,hits,neg,val=score_record(rec)
            if score < 12: continue
            title=first(rec,["title","name","tender_title","notice_title","description_title"])
            deadline=first(rec,["deadline","submission_deadline","closing_date","close_date","tender_deadline"])
            buyer=first(rec,["buyer","buyer_name","authority","contracting_authority","organisation","organization"])
            rows.append({
                "candidate_id":cid,
                "score":score,
                "source_family":source_family(rec,cid),
                "title":title,
                "buyer":buyer,
                "deadline":deadline,
                "estimated_value":val,
                "positive_hits":hits,
                "negative_hits":neg,
                "record":rec,
            })
    rows.sort(key=lambda x:(x["score"], x.get("estimated_value") or 0), reverse=True)
    top=rows[:args.top]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out,"w",encoding="utf-8") as f:
        for r in top: f.write(json.dumps(r,ensure_ascii=False)+"\n")

    # Diversity-aware selection: reserve source-specific floors, then fill by score.
    floors={"TED":90,"UK":45,"IE":35,"CA":35,"QC":20,"DE":25,"FR":25,"AU":15,"NZ":15}
    selected=[]; used=set()
    for src,n in floors.items():
        for r in [x for x in top if x["source_family"]==src][:n]:
            if r["candidate_id"] not in used:
                selected.append(r); used.add(r["candidate_id"])
    for r in top:
        if len(selected)>=args.select: break
        if r["candidate_id"] not in used:
            selected.append(r); used.add(r["candidate_id"])
    selected=selected[:args.select]
    manifest={
        "wide_read_run_id":args.run_id,
        "default_preliminary_score":82,
        "status":"DCE_PENDING",
        "selection_reason":"Worldwide high-recall lean-services prefilter only; DCE required before any supergreen verdict.",
        "candidate_ids":[r["candidate_id"] for r in selected]
    }
    with open(args.selection,"w",encoding="utf-8") as f:
        f.write(json.dumps(manifest,ensure_ascii=False)+"\n")
    summary={
        "source_run":args.run_id,
        "eligible_prefilter":len(rows),
        "saved_top":len(top),
        "selected_for_dce":len(selected),
        "by_source":{},
        "generated_at":datetime.now(timezone.utc).isoformat()
    }
    for r in selected: summary["by_source"][r["source_family"]]=summary["by_source"].get(r["source_family"],0)+1
    with open(args.out+".summary.json","w",encoding="utf-8") as f: json.dump(summary,f,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
