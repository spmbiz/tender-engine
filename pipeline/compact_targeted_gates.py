from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CATS = [
    "turnover_financial","references_experience","insurance","team_cvs","language",
    "certifications","onsite_geography","subcontracting_consortium","hosting_security_data",
    "award_criteria","payment","deadline_submission","deliverables_scope",
]

def load(path: Path):
    try: return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception: return None

def clean(s: str, n: int = 1800) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]

def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+","-",s).strip("-")[:120] or "candidate"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True); ap.add_argument("--out",required=True)
    ap.add_argument("--split-dir"); ap.add_argument("--max-snippets",type=int,default=4)
    args=ap.parse_args(); root=Path(args.root); out=[]
    split=Path(args.split_dir) if args.split_dir else None
    if split: split.mkdir(parents=True,exist_ok=True)
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir(): continue
        c=load(candidate/"candidate.json") or {}; m=load(candidate/"manifest.json") or {}; g=load(candidate/"gate_snippets.json") or {}
        cid=c.get("candidate_id") or g.get("candidate_id") or m.get("candidate_id") or candidate.name
        rec={
            "candidate_id":cid,"title":c.get("title"),"buyer":c.get("buyer"),"deadline":c.get("deadline"),
            "estimated_value":c.get("estimated_value"),"portal":c.get("portal") or c.get("portal_key") or c.get("source"),
            "source_url":c.get("source_url") or c.get("notice_url") or c.get("url"),"manifest_status":m.get("status"),
            "resolution":m.get("resolution"),"files":[{"name":x.get("name"),"size":x.get("size"),"source":x.get("source") or x.get("url")} for x in (m.get("files") or []) if isinstance(x,dict)],
            "corpus_chars":g.get("corpus_chars"),"evidence_counts":g.get("evidence_counts") or {},"gates":{}
        }
        cats=g.get("categories") or {}
        for cat in CATS:
            rec["gates"][cat]=[{"match":h.get("match"),"snippet":clean(h.get("snippet"))} for h in (cats.get(cat) or [])[:args.max_snippets] if isinstance(h,dict)]
        out.append(rec)
        if split: (split/f"{slug(str(cid))}.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps({"candidate_count":len(out),"candidates":out},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"candidate_count":len(out),"out":args.out,"split_dir":str(split) if split else None}))

if __name__=="__main__": main()
