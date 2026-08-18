from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

CANONICAL_PATTERNS = {
    "entity_geography": [
        r"eligible economic operator", r"eligibility", r"participation is reserved", r"reserved participation", r"economic operator", r"country of establishment",
        r"registered in", r"local presence", r"resident", r"nationality", r"EU member state", r"EEA", r"third countr", r"sanctions", r"exclusion grounds",
        r"opérateur économique", r"conditions de participation", r"participation réservée", r"pays d'établissement", r"implantation locale",
        r"wirtschaftsteilnehmer", r"teilnahmeberechtigt", r"niederlassung", r"teilnahme vorbehalten",
    ],
    "turnover_financial": [
        r"turnover", r"annual turnover", r"minimum turnover", r"financial capacity", r"economic and financial", r"financial standing", r"balance sheet",
        r"chiffre d'affaires", r"capacit[ée] financi", r"situation financière", r"omzet", r"financi[eë]le draagkracht", r"umsatz", r"wirtschaftliche.*leistungsfähigkeit",
    ],
    "references_experience": [
        r"reference[s]?", r"similar contract", r"similar project", r"comparable contract", r"professional experience", r"previous experience",
        r"références?", r"prestations similaires", r"expérience professionnelle", r"ervaring", r"referentie", r"vergleichbare referenz", r"referenzprojekt",
    ],
    "certifications_partner": [
        r"certification", r"accreditation", r"ISO\s?\d+", r"certificate", r"authori[sz]ed reseller", r"reseller status", r"partner status", r"manufacturer authori[sz]ation",
        r"certificat", r"accréditation", r"revendeur agréé", r"partenaire agréé", r"autorisation du fabricant", r"certificering", r"geautoriseerde partner",
        r"zertifizierung", r"herstellerautorisierung", r"partnerstatus",
    ],
    "staffing_team": [
        r"curriculum vitae", r"\bCVs?\b", r"key personnel", r"project manager", r"team members", r"minimum team", r"named personnel", r"staffing",
        r"équipe", r"chef de projet", r"personnel clé", r"effectif minimum", r"sleutelpersoneel", r"projectleider", r"projektleiter", r"schlüsselpersonal",
    ],
    "insurance_bonds": [
        r"insurance", r"professional indemnity", r"public liability", r"employer.?s liability", r"product liability", r"cyber liability", r"performance bond", r"bid bond", r"bank guarantee",
        r"assurance", r"responsabilit[ée] civile", r"garantie bancaire", r"caution", r"verzekering", r"beroepsaansprakelijkheid", r"haftpflicht", r"bürgschaft",
    ],
    "subcontracting_consortium": [
        r"subcontract", r"consortium", r"joint tender", r"rely on the capacities", r"group of economic operators", r"third party capacities",
        r"sous-trait", r"groupement", r"cotrait", r"capacités d'autres entités", r"onderaannem", r"combinatie", r"unterauftrag", r"bietergemeinschaft",
    ],
    "deliverables_scope": [
        r"deliverable", r"scope of work", r"statement of work", r"specification", r"requirements", r"outputs?", r"volume", r"quantity", r"milestone",
        r"livrable", r"cahier des charges", r"prestations", r"spécifications", r"quantités", r"opdracht", r"vereisten", r"leistungsbeschreibung", r"leistungsumfang",
    ],
    "sla_onsite": [
        r"SLA", r"service level", r"response time", r"resolution time", r"availability", r"uptime", r"on[- ]?site", r"site visit", r"in person", r"physical meeting", r"travel", r"local presence",
        r"sur site", r"présentiel", r"délai d'intervention", r"temps de réponse", r"déplacement", r"ter plaatse", r"fysieke vergadering", r"vor ort", r"reaktionszeit",
    ],
    "term_value": [
        r"contract duration", r"duration of the contract", r"initial term", r"renewal", r"extension", r"option year", r"estimated value", r"maximum value", r"budget", r"framework ceiling",
        r"durée du marché", r"reconduct", r"prolongation", r"valeur estimée", r"montant maximum", r"budget", r"looptijd", r"verlenging", r"geraamde waarde", r"vertragslaufzeit", r"geschätzter wert",
    ],
    "award_criteria": [
        r"award criteria", r"evaluation criteria", r"quality.*price", r"price.*quality", r"marks", r"weighting", r"minimum score", r"pass mark",
        r"critères? d'attribution", r"critères? de jugement", r"pondération", r"notation", r"note minimale", r"gunningscriteria", r"weging", r"zuschlagskriterien", r"wertung",
    ],
    "forms_signatures": [
        r"form of tender", r"mandatory form", r"signature", r"signed by", r"eESPD", r"ESPD", r"declaration", r"appendix", r"schedule.*complete", r"power of attorney",
        r"acte d'engagement", r"formulaire obligatoire", r"signature", r"déclaration", r"annexe.*compléter", r"mandat", r"verplicht formulier", r"handtekening", r"erklärung", r"unterschrift",
    ],
    "submission": [
        r"deadline", r"closing date", r"submission date", r"tender submission", r"validity of tender", r"submission portal", r"electronic submission", r"language of tender", r"language requirement",
        r"date limite", r"remise des offres", r"validité de l'offre", r"langue de l'offre", r"plateforme de dépôt", r"uiterste datum", r"indiening", r"taal van de inschrijving",
        r"angebotsfrist", r"einreichung", r"sprache des angebots",
    ],
    "ip_data_security": [
        r"intellectual property", r"copyright", r"licen[cs]ing", r"source code", r"source files", r"ownership", r"data protection", r"GDPR", r"data residency", r"hosting", r"cyber", r"security requirement", r"penetration test",
        r"propriété intellectuelle", r"droits d'auteur", r"fichiers sources", r"code source", r"RGPD", r"hébergement", r"protection des données", r"sécurité", r"AVG", r"gegevensbescherming",
        r"urheberrecht", r"quellcode", r"datenschutz", r"hostingstandort", r"informationssicherheit",
    ],
    "payment_tax": [
        r"payment", r"invoice", r"milestone payment", r"advance payment", r"days after invoice", r"tax clearance", r"tax compliance", r"social security",
        r"paiement", r"facture", r"acompte", r"échéancier", r"attestation fiscale", r"cotisations sociales", r"betaling", r"factuur", r"steuer", r"rechnung",
    ],
}

LEGACY_ALIASES = {
    "references_experience": "references_experience",
    "insurance": "insurance_bonds",
    "tax_clearance": "payment_tax",
    "team_cvs": "staffing_team",
    "language": "submission",
    "certifications": "certifications_partner",
    "onsite_geography": "sla_onsite",
    "subcontracting_consortium": "subcontracting_consortium",
    "hosting_security_data": "ip_data_security",
    "award_criteria": "award_criteria",
    "payment": "payment_tax",
    "deadline_submission": "submission",
    "deliverables_scope": "deliverables_scope",
}

RAW_MACHINE_EXTS = {".xml", ".html", ".htm", ".json"}


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {} if default is None else default


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


def empty_categories() -> dict:
    canonical = {name: [] for name in CANONICAL_PATTERNS}
    aliases = {alias: canonical[target] for alias, target in LEGACY_ALIASES.items()}
    return {**canonical, **aliases}


def extract_categories(text: str) -> dict:
    canonical = {name: snippets(text, pats) for name, pats in CANONICAL_PATTERNS.items()}
    aliases = {alias: canonical[target] for alias, target in LEGACY_ALIASES.items()}
    return {**canonical, **aliases}


def _document_for_span(start: int, end: int, docs: list[dict]) -> dict | None:
    best = None
    best_overlap = 0
    for doc in docs:
        try:
            ds = int(doc.get("corpus_start"))
            de = int(doc.get("corpus_end"))
        except Exception:
            continue
        overlap = max(0, min(end, de) - max(start, ds))
        if overlap > best_overlap:
            best = doc
            best_overlap = overlap
    return best


def _annotate_categories(categories: dict, docs: list[dict]) -> dict[str, int]:
    attributed = 0
    unattributed = 0
    machine_format = 0
    # Aliases point to the same list objects. Mutate canonical lists once.
    for gate in CANONICAL_PATTERNS:
        for item in categories.get(gate) or []:
            if not isinstance(item, dict):
                continue
            doc = _document_for_span(int(item.get("start") or 0), int(item.get("end") or 0), docs)
            if not doc:
                item["source"] = None
                item["provenance_strength"] = "UNATTRIBUTED_CORPUS"
                unattributed += 1
                continue
            source_path = str(doc.get("path") or doc.get("name") or "") or None
            suffix = Path(source_path or "").suffix.casefold()
            item.update({
                "source": source_path,
                "source_url": doc.get("source_url"),
                "source_sha256": doc.get("sha256"),
                "source_kind": doc.get("kind"),
                "source_provenance_match": doc.get("source_provenance_match"),
                "source_corpus_start": doc.get("corpus_start"),
                "source_corpus_end": doc.get("corpus_end"),
                "raw_machine_format": suffix in RAW_MACHINE_EXTS,
                "provenance_strength": "SOURCE_URL_ATTRIBUTED" if doc.get("source_url") else "DOCUMENT_HASH_ATTRIBUTED",
            })
            attributed += 1
            machine_format += int(suffix in RAW_MACHINE_EXTS)
    return {"attributed": attributed, "unattributed": unattributed, "raw_machine_format": machine_format}


def process(root: Path):
    corpus_path = root / "corpus.txt"
    if not corpus_path.exists():
        return None
    text = corpus_path.read_text(encoding="utf-8", errors="replace")
    evidence = load_json(root / "evidence_quality.json", {})
    gate_ready = bool(evidence.get("gate_readiness")) if evidence else None
    docs_raw = load_json(root / "document_index.json", [])
    docs = docs_raw if isinstance(docs_raw, list) else []

    if evidence and not gate_ready:
        gates = empty_categories()
        provenance = {"attributed": 0, "unattributed": 0, "raw_machine_format": 0}
        result = {
            "candidate_id": None,
            "corpus_chars": len(text),
            "gate_readiness": False,
            "skipped_due_to_evidence_quality": True,
            "content_quality": evidence.get("content_quality"),
            "derived_status": evidence.get("derived_status"),
            "canonical_gate_names": list(CANONICAL_PATTERNS),
            "categories": gates,
            "evidence_counts": {k: 0 for k in gates},
            "document_index_available": bool(docs),
            "snippet_provenance": provenance,
            "warning": "Mandatory-gate extraction blocked because authoritative DCE content was not proven. Do not infer eligibility from this corpus.",
        }
    else:
        gates = extract_categories(text)
        provenance = _annotate_categories(gates, docs)
        result = {
            "candidate_id": None,
            "corpus_chars": len(text),
            "gate_readiness": bool(gate_ready) if gate_ready is not None else None,
            "skipped_due_to_evidence_quality": False,
            "content_quality": evidence.get("content_quality") if evidence else None,
            "derived_status": evidence.get("derived_status") if evidence else None,
            "canonical_gate_names": list(CANONICAL_PATTERNS),
            "categories": gates,
            "evidence_counts": {k: len(v) for k, v in gates.items()},
            "document_index_available": bool(docs),
            "snippet_provenance": provenance,
            "warning": "These are retrieval snippets, not eligibility verdicts. Each attributed snippet carries its exact extracted document path/hash and, where available, original source URL. GPT/human review must still resolve every mandatory gate explicitly.",
        }

    candidate_path = root / "candidate.json"
    if candidate_path.exists():
        try:
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            result["candidate_id"] = candidate.get("candidate_id")
        except Exception:
            pass
    (root / "gate_snippets.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "root": str(root),
        "candidate_id": result.get("candidate_id"),
        "gate_readiness": result.get("gate_readiness"),
        "skipped": result.get("skipped_due_to_evidence_quality"),
        "canonical_gate_names": result.get("canonical_gate_names"),
        "evidence_counts": result["evidence_counts"],
        "snippet_provenance": result.get("snippet_provenance"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    ap.add_argument("--workers", type=int, default=int(os.getenv("DCE_GATE_WORKERS", "2")))
    args = ap.parse_args()
    base = Path(args.root)
    roots = sorted(set(p.parent for p in base.rglob("corpus.txt")))
    workers = max(1, min(args.workers, len(roots) or 1))
    results = []

    if workers == 1:
        for root in roots:
            rec = process(root)
            if rec:
                results.append(rec)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(process, root): root for root in roots}
            for fut in as_completed(futs):
                try:
                    rec = fut.result()
                except Exception as exc:
                    rec = {"root": str(futs[fut]), "candidate_id": None, "error": repr(exc), "evidence_counts": {}}
                if rec:
                    results.append(rec)

    results.sort(key=lambda r: r.get("root", ""))
    print(json.dumps({
        "workers": workers,
        "candidates": len(roots),
        "gate_ready": sum(1 for r in results if r.get("gate_readiness")),
        "skipped_unverified": sum(1 for r in results if r.get("skipped")),
        "attributed_snippets": sum(int((r.get("snippet_provenance") or {}).get("attributed") or 0) for r in results),
        "unattributed_snippets": sum(int((r.get("snippet_provenance") or {}).get("unattributed") or 0) for r in results),
        "canonical_gate_names": list(CANONICAL_PATTERNS),
        "results": results,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
