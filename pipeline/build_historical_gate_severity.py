#!/usr/bin/env python3
from __future__ import annotations

"""Build a compact qualitative gate-severity review from historical DCE output.

The script consumes already-extracted authoritative gate_snippets.json files.
It does not invent pass/fail. It labels *signals* conservatively and preserves a
short evidence context so GPT/human review can verify the interpretation.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HARD_PATTERNS = {
    "turnover_minimum": [
        r"chiffre d['’]affaires.{0,180}(?:minimum|minimal|au moins|sup[eé]rieur|égal|exig)",
        r"(?:minimum|minimal).{0,100}chiffre d['’]affaires",
        r"minimum turnover|turnover.{0,120}(?:at least|minimum|required)",
    ],
    "references_explicit": [
        r"(?:au moins|minimum|minimum de|justifier de).{0,120}(?:références?|prestations similaires)",
        r"(?:références?|prestations similaires).{0,180}(?:trois|3|deux|2|dernières années|derniers exercices|minimum|au moins)",
        r"(?:at least|minimum).{0,100}(?:references?|similar contracts?|similar projects?)",
    ],
    "named_team_cv": [
        r"(?:cv|curriculum vitae).{0,160}(?:chef de projet|équipe|intervenant|personnel|consultant)",
        r"(?:chef de projet|équipe|personnel clé|intervenants?).{0,180}(?:cv|curriculum vitae|expérience minimale|années d'expérience)",
        r"(?:key personnel|project manager|team).{0,160}(?:cv|curriculum vitae|minimum experience)",
    ],
    "mandatory_onsite": [
        r"(?:obligatoire|doit|devra|exig).{0,140}(?:sur site|présentiel|déplacement|réunion physique)",
        r"(?:sur site|présentiel).{0,140}(?:obligatoire|doit|devra|exig)",
        r"(?:mandatory|required|shall).{0,120}(?:on[- ]site|in person|site visit)",
    ],
    "certification_mandatory": [
        r"(?:certificat|certification|accréditation|iso\s?\d+).{0,180}(?:obligatoire|exig|required|doit|devra)",
        r"(?:obligatoire|exig|required).{0,160}(?:certificat|certification|accréditation|iso\s?\d+)",
    ],
    "insurance_mandatory": [
        r"(?:assurance|responsabilité civile|garantie).{0,180}(?:obligatoire|doit|devra|exig|minim|montant)",
        r"(?:professional indemnity|public liability|insurance).{0,160}(?:required|minimum|shall)",
    ],
    "subcontracting_restricted": [
        r"sous[- ]trait.{0,180}(?:interdit|limité|autorisation|agrément|acceptation|déclar)",
        r"(?:interdit|limité|autorisation|agrément|acceptation).{0,160}sous[- ]trait",
        r"subcontract.{0,160}(?:prohibit|limit|approval|consent|required)",
    ],
    "samples_or_proofs": [
        r"(?:échantillon|épreuve|bon [àa] tirer|\bBAT\b|maquette).{0,180}(?:fourni|remis|obligatoire|exig|validation)",
        r"(?:sample|proof).{0,160}(?:required|submit|approval)",
    ],
    "eco_print_requirement": [
        r"(?:fsc|pefc|écolabel|eco[- ]?label|papier recyclé|encres? végétales?|imprim['’]?vert).{0,180}",
    ],
    "security_or_data": [
        r"(?:rgpd|gdpr|hébergement|données personnelles|sécurité|confidentialité|propriété intellectuelle|fichiers sources).{0,180}",
    ],
}

CANONICAL = [
    "entity_geography","turnover_financial","references_experience","certifications_partner",
    "staffing_team","insurance_bonds","subcontracting_consortium","deliverables_scope","sla_onsite",
    "term_value","award_criteria","forms_signatures","submission","ip_data_security","payment_tax",
]


def compact(s: str, n: int = 520) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n]


def best_context(snips: list[dict], pats: list[str]) -> dict | None:
    for item in snips or []:
        text = compact(str(item.get("snippet") or ""), 2200)
        for pat in pats:
            m = re.search(pat, text, re.I | re.S)
            if m:
                a=max(0,m.start()-170); b=min(len(text),m.end()+220)
                return {"match": compact(m.group(0),180), "context": compact(text[a:b],520)}
    return None


def candidate_roots(root: Path):
    for g in sorted(root.rglob("gate_snippets.json")):
        yield g.parent


def review_one(root: Path) -> dict | None:
    try:
        gates=json.loads((root/"gate_snippets.json").read_text(encoding="utf-8"))
        candidate=json.loads((root/"candidate.json").read_text(encoding="utf-8"))
        evidence=json.loads((root/"evidence_quality.json").read_text(encoding="utf-8")) if (root/"evidence_quality.json").exists() else {}
        manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8")) if (root/"manifest.json").exists() else {}
    except Exception:
        return None
    if not gates.get("gate_readiness"):
        return None
    cats=gates.get("categories") or {}
    signals={k:len(cats.get(k) or []) for k in CANONICAL}
    hard={}
    for name,pats in HARD_PATTERNS.items():
        pool=[]
        # Search all canonical snippets because hard wording can be captured under
        # more than one canonical gate category.
        seen=set()
        for cname in CANONICAL:
            for item in cats.get(cname) or []:
                key=(item.get("start"),item.get("end"),item.get("snippet"))
                if key not in seen:
                    seen.add(key); pool.append(item)
        hit=best_context(pool,pats)
        hard[name] = {"signal": bool(hit), "evidence": hit}
    return {
        "candidate_id":candidate.get("candidate_id"),
        "sub_niche":candidate.get("historical_sub_niche"),
        "buyer":candidate.get("buyer"),
        "title":candidate.get("title"),
        "portal":candidate.get("portal"),
        "resolver_status":manifest.get("status"),
        "content_quality":evidence.get("content_quality"),
        "files":[{"name":f.get("name"),"size":f.get("size"),"source_url":f.get("source_url")} for f in (manifest.get("files") or [])],
        "canonical_gate_signal_counts":signals,
        "hard_gate_signals":hard,
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); ap.add_argument("--out",required=True); a=ap.parse_args()
    root=Path(a.root); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    rows=[r for p in candidate_roots(root) if (r:=review_one(p))]
    rows.sort(key=lambda r:(str(r.get("sub_niche")),str(r.get("title"))))
    with (out/"gate_severity_candidates.jsonl").open("w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    by=defaultdict(lambda:{"sample":0,"hard":Counter(),"canonical":Counter()})
    for r in rows:
        x=by[str(r.get("sub_niche") or "UNKNOWN")]; x["sample"]+=1
        for k,v in r["hard_gate_signals"].items():
            if v["signal"]: x["hard"][k]+=1
        for k,v in r["canonical_gate_signal_counts"].items():
            if v: x["canonical"][k]+=1
    summary={
        "contract":"HISTORICAL_GATE_SEVERITY_REVIEW_V1","gate_ready_candidates":len(rows),
        "final_verdict_allowed":False,
        "warning":"Pattern-backed severity signals over tiny historical samples; absence of a match is UNKNOWN, never proof that a requirement did not exist.",
        "subniches":{k:{"sample":v["sample"],"hard_signal_candidate_counts":dict(v["hard"]),"canonical_signal_candidate_counts":dict(v["canonical"])} for k,v in sorted(by.items())},
    }
    (out/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Historical Gate Severity Review v1","",f"Gate-ready historical DCEs reviewed: **{len(rows)}**.","","Absence of a signal is UNKNOWN; this is not a pass/fail model.",""]
    for niche,v in summary["subniches"].items():
        lines.append(f"## {niche} — n={v['sample']}")
        hard=v["hard_signal_candidate_counts"]
        lines.append("Hard wording signals: "+(", ".join(f"{k} {n}/{v['sample']}" for k,n in sorted(hard.items())) if hard else "none detected by conservative patterns"))
        lines.append("")
    (out/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=="__main__": main()
