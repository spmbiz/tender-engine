#!/usr/bin/env python3
from __future__ import annotations

"""Extract conservative, evidence-backed business signals from true print DCE corpora.

Input is expected to be the fail-closed downstream BOAMP DCE worker output.
Only candidates whose evidence_quality.json says gate_readiness=true are read.
Every extracted item carries a short source context. Absence is UNKNOWN.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

PATTERNS = {
    "minimum_turnover": [
        r"chiffre d['’]affaires.{0,120}(?:minimum|minimal|au moins|sup[eé]rieur|doit être).{0,100}(?:\d[\d\s.,]*\s*(?:€|euros?)|\d+\s*%)",
        r"(?:minimum|minimal).{0,80}chiffre d['’]affaires.{0,120}(?:\d[\d\s.,]*\s*(?:€|euros?)|\d+\s*%)",
    ],
    "similar_references": [
        r"(?:liste|présentation).{0,80}(?:principaux|principales).{0,80}(?:services|fournitures|prestations).{0,180}(?:trois|3).{0,40}(?:dernières|derniers).{0,30}années",
        r"références? professionnelles?.{0,180}(?:prestations?|marchés?|travaux) similaires?",
        r"références?.{0,100}(?:prestations?|marchés?) similaires?.{0,100}(?:trois|3|deux|2|minimum|au moins)",
        r"(?:au moins|minimum(?: de)?)\s+\d+.{0,40}références?",
    ],
    "named_team_cv": [
        r"(?:cv|curriculum vitae).{0,140}(?:chef de projet|équipe|intervenant|personnel clé|responsable)",
        r"(?:chef de projet|équipe|intervenants?|personnel clé).{0,140}(?:cv|curriculum vitae|années d['’]expérience)",
    ],
    "mandatory_insurance": [
        r"attestation.{0,40}assurance.{0,140}(?:doit|devra|obligatoire|à fournir|exig)",
        r"assurance.{0,60}responsabilit[eé] civile.{0,140}(?:doit|devra|obligatoire|minimum|montant|à fournir|exig)",
    ],
    "subcontract_restriction": [
        r"sous[- ]traitance.{0,160}(?:interdite|limitée|autorisation|agrément|acceptation|déclaration obligatoire)",
        r"(?:interdiction|limitation|autorisation|agrément|acceptation).{0,120}sous[- ]trait",
    ],
    "mandatory_sample_or_proof": [
        r"échantillons?.{0,160}(?:obligatoire|à remettre|à fournir|doit|devra|exig)",
        r"(?:bon à tirer|\bBAT\b|épreuve).{0,140}(?:obligatoire|validation|doit|devra|soumis|à fournir)",
    ],
    "mandatory_eco_cert": [
        r"(?:FSC|PEFC|écolabel|imprim['’]?vert).{0,160}(?:obligatoire|exig|doit|devra|certifi)",
        r"(?:obligatoire|exig|doit|devra).{0,120}(?:FSC|PEFC|écolabel|imprim['’]?vert)",
    ],
    "quantity_or_run": [
        r"(?:tirage|quantit[eé]|nombre d['’]exemplaires|exemplaires?).{0,120}\b\d[\d\s.,]{2,}\b",
        r"\b\d[\d\s.,]{2,}\s+exemplaires?\b",
    ],
    "paper_format_weight": [
        r"(?:format\s+(?:A[0-6]|\d+\s*[x×]\s*\d+)|\bA[0-6]\b).{0,160}(?:\d{2,3}\s*g(?:/m[²2])?|papier|grammage)",
        r"(?:papier|grammage).{0,120}\d{2,3}\s*g(?:/m[²2])?",
    ],
    "delivery_logistics": [r"(?:livraison|expédition|routage|mise sous pli|conditionnement|stockage).{0,200}"],
    "finishing": [r"(?:façonnage|agraf|pellicul|reliure|pliage|massicot|dos carré|encoll).{0,180}"],
    "source_files_ip": [r"(?:fichiers? sources?|propriété intellectuelle|droits? d['’]auteur|cession des droits).{0,180}"],
}

# Keep these intentionally narrow. Candidate values are not reported unless a
# non-zero plausible percentage follows an explicit award-criterion phrase.
PRICE_RX = re.compile(r"(?:crit[eè]re\s+(?:n[°o]\s*\d+\s*:\s*)?(?:prix|co[uû]t)|pond[eé]ration\s+(?:du\s+)?prix).{0,35}?(\d{1,3}(?:[,.]\d+)?)\s*%", re.I | re.S)
TECH_RX = re.compile(r"(?:crit[eè]re\s+(?:n[°o]\s*\d+\s*:\s*)?(?:valeur technique|qualit[eé])|pond[eé]ration\s+(?:de\s+la\s+)?(?:valeur technique|qualit[eé])).{0,35}?(\d{1,3}(?:[,.]\d+)?)\s*%", re.I | re.S)
DURATION_RX = re.compile(r"(?:durée du marché|durée de l['’]accord[- ]cadre|durée du contrat).{0,120}(\d{1,2})\s*(mois|ans?|années?)", re.I | re.S)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def contexts(text: str, regexes: list[str], max_hits=4, before=150, after=260):
    out=[]; seen=set()
    for pat in regexes:
        for m in re.finditer(pat,text,re.I|re.S):
            a=max(0,m.start()-before); b=min(len(text),m.end()+after)
            c=clean(text[a:b]); key=c[:220].casefold()
            if key in seen: continue
            seen.add(key); out.append({"match":clean(m.group(0))[:200],"context":c[:650]})
            if len(out)>=max_hits: return out
    return out


def _pct_values(rx: re.Pattern, text: str) -> list[str]:
    out=[]
    for m in rx.finditer(text):
        raw=m.group(1).replace(",",".")
        try: value=float(raw)
        except Exception: continue
        if not (0 < value <= 100):
            continue
        norm=(str(int(value)) if value.is_integer() else str(value))
        if norm not in out: out.append(norm)
        if len(out)>=5: break
    return out


def scalar_hits(text: str):
    return {
        "price_weight_pct_candidates": _pct_values(PRICE_RX,text),
        "technical_or_quality_weight_pct_candidates": _pct_values(TECH_RX,text),
        "duration_candidates": [f"{m.group(1)} {m.group(2)}" for m in list(DURATION_RX.finditer(text))[:5]],
    }


def iter_candidates(root: Path):
    for p in sorted(root.rglob("evidence_quality.json")):
        d=p.parent
        try:
            e=json.loads(p.read_text(encoding="utf-8")); c=json.loads((d/"candidate.json").read_text(encoding="utf-8")); m=json.loads((d/"manifest.json").read_text(encoding="utf-8"))
        except Exception: continue
        if not e.get("gate_readiness"): continue
        niche=str(c.get("historical_sub_niche") or "")
        if "print" not in niche.casefold() and "printing" not in niche.casefold(): continue
        corpus=(d/"corpus.txt").read_text(encoding="utf-8",errors="replace") if (d/"corpus.txt").exists() else ""
        yield d,c,m,e,corpus


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); ap.add_argument("--out",required=True); a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); rows=[]
    for d,c,m,e,text in iter_candidates(Path(a.root)):
        sig={k:contexts(text,pats) for k,pats in PATTERNS.items()}
        rows.append({"candidate_id":c.get("candidate_id"),"sub_niche":c.get("historical_sub_niche"),"buyer":c.get("buyer"),"title":c.get("title"),"content_quality":e.get("content_quality"),"files":[{"name":x.get("name"),"source_url":x.get("source_url"),"size":x.get("size")} for x in (m.get("files") or [])],"signals":sig,"scalars":scalar_hits(text)})
    rows.sort(key=lambda x:(str(x.get("sub_niche")),str(x.get("title"))))
    with (out/"print_dce_briefs.jsonl").open("w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    summary={"contract":"HISTORICAL_PRINT_DCE_BUSINESS_BRIEF_V1","true_gate_ready_print_dces":len(rows),"final_verdict_allowed":False,"warning":"Strict evidence extraction from tiny historical sample. Empty signal = UNKNOWN, not absent requirement.","signal_candidate_counts":{k:sum(bool(r['signals'][k]) for r in rows) for k in PATTERNS},"subniches":dict(Counter(str(r.get('sub_niche')) for r in rows))}
    (out/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Historical Print DCE Business Brief v1","",f"True gate-ready print DCEs: **{len(rows)}**.","","Absence of a signal remains UNKNOWN.",""]
    for r in rows:
        lines += [f"## {r['title']}",f"Buyer: {r['buyer']} · Sub-niche: {r['sub_niche']}"]
        found=[k for k,v in r['signals'].items() if v]; lines.append("Signals: "+(", ".join(found) if found else "none detected by strict patterns"))
        if r['scalars']['price_weight_pct_candidates']: lines.append("Price-weight candidates: "+", ".join(r['scalars']['price_weight_pct_candidates']))
        if r['scalars']['technical_or_quality_weight_pct_candidates']: lines.append("Quality/technical-weight candidates: "+", ".join(r['scalars']['technical_or_quality_weight_pct_candidates']))
        if r['scalars']['duration_candidates']: lines.append("Duration candidates: "+", ".join(r['scalars']['duration_candidates']))
        lines.append("")
    (out/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=="__main__": main()
