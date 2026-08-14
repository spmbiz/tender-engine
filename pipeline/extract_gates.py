from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERNS = {
    "turnover_financial": [
        r"turnover", r"annual turnover", r"financial capacity", r"economic and financial",
        r"chiffre d'affaires", r"capacit[ée] financi", r"omzet", r"financi[eë]le draagkracht",
    ],
    "references_experience": [
        r"reference[s]?", r"similar contract", r"similar project", r"professional experience",
        r"références?", r"prestations similaires", r"expérience professionnelle", r"ervaring", r"referentie",
    ],
    "insurance": [
        r"insurance", r"professional indemnity", r"public liability", r"employer.?s liability", r"cyber liability",
        r"assurance", r"responsabilit[ée] civile", r"garantie d'assurance", r"verzekering", r"beroepsaansprakelijkheid",
    ],
    "tax_clearance": [
        r"tax clearance", r"tax compliance", r"fiscal", r"social security", r"attestation fiscale",
        r"obligations fiscales", r"cotisations sociales", r"belast", r"sociale zekerheid",
    ],
    "team_cvs": [
        r"curriculum vitae", r"\bCVs?\b", r"key personnel", r"project manager", r"team members",
        r"équipe", r"chef de projet", r"personnel clé", r"sleutelpersoneel", r"projectleider",
    ],
    "language": [
        r"language requirement", r"English language", r"French language", r"official language",
        r"langue", r"français", r"anglais", r"néerlandais", r"taal", r"Nederlands",
    ],
    "certifications": [
        r"certification", r"accreditation", r"ISO\s?\d+", r"certificate", r"certificat", r"accréditation", r"certificering",
    ],
    "onsite_geography": [
        r"on[- ]?site", r"site visit", r"in person", r"physical meeting", r"travel", r"local presence",
        r"sur site", r"présentiel", r"déplacement", r"réunion.*sur site", r"ter plaatse", r"fysieke vergadering",
    ],
    "subcontracting_consortium": [
        r"subcontract", r"consortium", r"joint tender", r"rely on the capacities", r"group of economic operators",
        r"sous-trait", r"groupement", r"cotrait", r"capacités d'autres entités", r"onderaannem", r"combinatie",
    ],
    "hosting_security_data": [
        r"hosting", r"SLA", r"service level", r"cyber", r"GDPR", r"data protection", r"security requirement",
        r"hébergement", r"RGPD", r"protection des données", r"sécurité", r"hosting", r"AVG",
    ],
    "award_criteria": [
        r"award criteria", r"quality.*price", r"price.*quality", r"marks", r"weighting",
        r"critères? d'attribution", r"pondération", r"notation", r"gunningscriteria", r"weging",
    ],
    "payment": [
        r"payment", r"invoice", r"milestone", r"advance payment", r"days after invoice",
        r"paiement", r"facture", r"acompte", r"échéancier", r"betaling", r"factuur",
    ],
    "deadline_submission": [
        r"deadline", r"closing date", r"submission date", r"tender submission", r"validity of tender",
        r"date limite", r"remise des offres", r"validité de l'offre", r"uiterste datum", r"indiening",
    ],
    "deliverables_scope": [
        r"deliverable", r"scope of work", r"specification", r"requirements", r"outputs?",
        r"livrable", r"cahier des charges", r"prestations", r"spécifications", r"opdracht", r"vereisten",
    ],
}


def snippets(text: str, regexes: list[str], window: int = 650, max_hits: int = 24):
    out = []
    seen = set()
    union = re.compile("|".join(f"(?:{p})" for p in regexes), re.I | re.S)
    for m in union.finditer(text):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        snip = text[start:end].strip()
        key = re.sub(r"\s+", " ", snip[:220]).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"match": m.group(0)[:120], "start": start, "end": end, "snippet": snip})
        if len(out) >= max_hits:
            break
    return out


def process(root: Path):
    corpus_path = root / "corpus.txt"
    if not corpus_path.exists():
        return None
    text = corpus_path.read_text(encoding="utf-8", errors="replace")
    gates = {name: snippets(text, pats) for name, pats in PATTERNS.items()}
    result = {
        "candidate_id": None,
        "corpus_chars": len(text),
        "categories": gates,
        "evidence_counts": {k: len(v) for k, v in gates.items()},
        "warning": "These are retrieval snippets, not eligibility verdicts. GPT must read the DCE/corpus and resolve each gate explicitly.",
    }
    candidate_path = root / "candidate.json"
    if candidate_path.exists():
        try:
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            result["candidate_id"] = candidate.get("candidate_id")
        except Exception:
            pass
    (root / "gate_snippets.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"root": str(root), "candidate_id": result.get("candidate_id"), "evidence_counts": result["evidence_counts"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    args = ap.parse_args()
    base = Path(args.root)
    results = []
    for corpus in base.rglob("corpus.txt"):
        rec = process(corpus.parent)
        if rec:
            results.append(rec)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
