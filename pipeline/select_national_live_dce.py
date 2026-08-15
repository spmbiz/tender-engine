from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LEAN = {
    "website": 28, "web site": 28, "cms": 30, "portal": 14, "hosting": 10,
    "graphic": 20, "design": 14, "branding": 22, "video": 22, "animation": 22,
    "audiovisual": 18, "marketing": 18, "social media": 22, "content": 14,
    "translation": 18, "transcription": 22, "printing": 14, "print": 10,
    "software": 16, "application": 12, "automation": 20, "digital": 10,
    "data": 8, "artificial intelligence": 22, "communication": 10,
    "maintenance": 8, "support": 5, "survey": 8, "research": 7,
}
HARD = {
    "construction": 45, "road": 35, "asphalt": 45, "roof": 35, "medical": 30,
    "pharmaceutical": 45, "catering": 30, "cleaning": 28, "vehicle": 25,
    "electricity supply": 35, "fuel": 35, "security guard": 35, "ammunition": 100,
}


def load_jsonl(path: Path):
    if not path.exists(): return []
    out=[]
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip(): continue
        try:x=json.loads(line)
        except Exception:continue
        if isinstance(x,dict):out.append(x)
    return out

def score(row):
    text=" "+re.sub(r"\s+"," "," ".join(str(row.get(k) or "") for k in ("title","description","procurement_method")).lower())+" "
    s=35;reasons=[]
    for term,pts in LEAN.items():
        if term in text:s+=pts;reasons.append(f"+{pts}:{term}")
    for term,pts in HARD.items():
        if term in text:s-=pts;reasons.append(f"-{pts}:{term}")
    # National low-value/open procedures are particularly valuable exploration targets.
    if any(x in text for x in ("small value","male vrednosti","evidenčno","low value","simplified","jednoduch")):
        s+=12;reasons.append("+12:national-low-value-signal")
    return max(0,min(89,s)),reasons

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default="national-discovery");ap.add_argument("--processed",default="benchmarks/national-live-processed.json");ap.add_argument("--out",default="generated/national_dce_candidates.jsonl");ap.add_argument("--limit",type=int,default=120);ap.add_argument("--minimum-score",type=int,default=48);args=ap.parse_args()
    processed=set()
    p=Path(args.processed)
    if p.exists():
        try:processed={str(x).casefold() for x in json.loads(p.read_text()).get("processed_candidate_ids",[])}
        except Exception:pass
    rows=[]
    for path in Path(args.root).rglob("current.jsonl"):
        rows.extend(load_jsonl(path))
    seen=set();scored=[]
    for row in rows:
        cid=str(row.get("candidate_id") or "").strip()
        if not cid or cid.casefold() in processed or cid.casefold() in seen:continue
        seen.add(cid.casefold())
        s,reasons=score(row)
        if s<args.minimum_score:continue
        rec=dict(row);rec["preliminary_score"]=s;rec["status"]="DCE_PENDING";rec["selection_reason"]="national_live_lean_prefilter:"+",".join(reasons[:12]);scored.append(rec)
    # Keep exploration across portals instead of allowing one large registry to monopolize the wave.
    scored.sort(key=lambda r:(-int(r.get("preliminary_score") or 0),str(r.get("deadline") or "9999"),str(r.get("candidate_id") or "")))
    by_portal={}
    for r in scored:by_portal.setdefault(str(r.get("portal") or "UNKNOWN"),[]).append(r)
    selected=[]
    while len(selected)<args.limit and any(by_portal.values()):
        for portal in sorted(by_portal,key=lambda x:(-len(by_portal[x]),x)):
            if by_portal[portal] and len(selected)<args.limit:selected.append(by_portal[portal].pop(0))
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8") as f:
        for r in selected:f.write(json.dumps(r,ensure_ascii=False)+"\n")
    summary={"raw_current_rows":len(rows),"processed_ids_loaded":len(processed),"lean_candidates":len(scored),"selected":len(selected),"minimum_score":args.minimum_score,"limit":args.limit,"portal_counts":{p:sum(1 for r in selected if str(r.get('portal'))==p) for p in sorted({str(r.get('portal')) for r in selected})}}
    out.with_suffix(out.suffix+".summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=="__main__":main()
