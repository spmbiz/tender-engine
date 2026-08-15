from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CATS = [
    "entity_geography",
    "turnover_financial",
    "references_experience",
    "certifications_partner",
    "staffing_team",
    "insurance_bonds",
    "subcontracting_consortium",
    "deliverables_scope",
    "sla_onsite",
    "term_value",
    "award_criteria",
    "forms_signatures",
    "submission",
    "ip_data_security",
    "payment_tax",
]


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def clean(s: str, n: int = 1800) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-snippets", type=int, default=4)
    args = ap.parse_args()
    root = Path(args.root)
    out=[]
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        c = load(candidate / "candidate.json") or {}
        m = load(candidate / "manifest.json") or {}
        q = load(candidate / "evidence_quality.json") or {}
        g = load(candidate / "gate_snippets.json") or {}
        cid = c.get("candidate_id") or g.get("candidate_id") or m.get("candidate_id") or candidate.name
        rec = {
            "candidate_id": cid,
            "title": c.get("title"),
            "buyer": c.get("buyer"),
            "deadline": c.get("deadline"),
            "estimated_value": c.get("estimated_value"),
            "currency": c.get("currency"),
            "portal": c.get("portal") or c.get("portal_key") or c.get("source"),
            "source_url": c.get("source_url") or c.get("notice_url") or c.get("url"),
            "manifest_status": m.get("status"),
            "derived_status": q.get("derived_status") or m.get("status"),
            "content_quality": q.get("content_quality"),
            "gate_readiness": bool(q.get("gate_readiness")),
            "evidence_quality": q,
            "resolution": m.get("resolution"),
            "files": [{"name":x.get("name"),"size":x.get("size"),"source":x.get("source") or x.get("url") or x.get("source_url")} for x in (m.get("files") or []) if isinstance(x,dict)],
            "corpus_chars": g.get("corpus_chars"),
            "evidence_counts": g.get("evidence_counts") or {},
            "canonical_gate_names": g.get("canonical_gate_names") or CATS[:-1],
            "gates": {},
            "review_template": {},
            "review_contract": (
                "Do not adjudicate mandatory gates unless gate_readiness is true. Fill each canonical gate with PASS/PASS_CONDITIONAL/FAIL_HARD/UNKNOWN/NOT_APPLICABLE and authoritative evidence. "
                "Do not assign score >=90 or FINAL_SUPER_GREEN until all potentially disqualifying gates are resolved with evidence."
            ),
        }
        cats = g.get("categories") or {}
        for cat in CATS:
            snippets=[]
            for hit in (cats.get(cat) or [])[:args.max_snippets]:
                if isinstance(hit,dict):
                    snippets.append({"match":hit.get("match"),"snippet":clean(hit.get("snippet"))})
            rec["gates"][cat]=snippets
            if cat != "payment_tax":
                rec["review_template"][cat] = {
                    "status": "UNKNOWN",
                    "evidence": [],
                    "evidence_candidates": snippets,
                    "notes": "",
                }
        out.append(rec)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"candidate_count":len(out),"candidates":out},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"candidate_count":len(out),"gate_ready":sum(1 for x in out if x['gate_readiness']),"out":args.out},indent=2))

if __name__ == "__main__":
    main()
