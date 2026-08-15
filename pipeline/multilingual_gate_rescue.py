from __future__ import annotations

import json
import re
from pathlib import Path

# Recall-oriented phrases only. These snippets are evidence candidates, never
# verdicts; the adjudicator + deterministic guard still decide PASS/UNKNOWN/FAIL.
EXTRA_PATTERNS: dict[str, list[str]] = {
    "entity_geography": [
        # PL
        r"warunki udzia[łl]u", r"podstawy wykluczenia", r"wykonawca zagraniczny", r"siedzib[ay] wykonawcy",
        # ES / IT / PT
        r"condiciones de participaci[oó]n", r"causas de exclusi[oó]n", r"operador econ[oó]mico",
        r"requisiti di partecipazione", r"cause di esclusione", r"operatore economico",
        r"condi[cç][oõ]es de participa[cç][aã]o", r"motivos de exclus[aã]o", r"operador econ[oó]mico",
        # CZ / SK
        r"podm[ií]nky [uú][cč]asti", r"d[uů]vody vylou[cč]en[ií]", r"podmienky [uú][cč]asti", r"d[oô]vody vyl[uú][cč]enia",
    ],
    "turnover_financial": [
        r"roczny obr[oó]t", r"minimalny obr[oó]t", r"zdolno[śs][ćc] finansowa", r"sytuacja ekonomiczna i finansowa",
        r"volumen anual de negocios", r"solvencia econ[oó]mica", r"capacidad financiera",
        r"fatturato annuo", r"capacit[aà] economica", r"capacit[aà] finanziaria",
        r"volume de neg[oó]cios anual", r"capacidade financeira",
        r"ro[cč]n[ií] obrat", r"ekonomick[aá] a finan[cč]n[ií] zp[uů]sobilost", r"ekonomick[eé] a finan[cč]n[eé] postavenie",
    ],
    "references_experience": [
        r"wykaz us[łl]ug", r"do[śs]wiadczenie wykonawcy", r"podobne zam[oó]wienia", r"referencje",
        r"experiencia profesional", r"servicios similares", r"relaci[oó]n de trabajos", r"referencias",
        r"esperienza professionale", r"servizi analoghi", r"servizi similari", r"referenze",
        r"experi[eê]ncia profissional", r"servi[cç]os semelhantes", r"refer[eê]ncias",
        r"seznam v[yý]znamn[yý]ch slu[žz]eb", r"obdobn[eé] zak[aá]zky", r"zoznam poskytnut[yý]ch slu[žz]ieb",
    ],
    "certifications_partner": [
        r"certyfikat", r"akredytacj", r"autoryzowany partner", r"autoryzacja producenta",
        r"certificaci[oó]n", r"acreditaci[oó]n", r"distribuidor autorizado", r"autorizaci[oó]n del fabricante",
        r"certificazione", r"accreditamento", r"partner autorizzato", r"autorizzazione del produttore",
        r"certifica[cç][aã]o", r"acredita[cç][aã]o", r"parceiro autorizado", r"autoriza[cç][aã]o do fabricante",
        r"certifik[aá]t", r"akreditace", r"autorizovan[yý] partner", r"autoriz[aá]cia v[yý]robcu",
    ],
    "staffing_team": [
        r"personel kluczowy", r"zesp[oó][łl] projektowy", r"kierownik projektu", r"[żz]yciorys", r"curriculum vitae",
        r"personal clave", r"equipo de proyecto", r"jefe de proyecto", r"curr[ií]culum",
        r"personale chiave", r"gruppo di progetto", r"responsabile di progetto", r"curriculum vitae",
        r"pessoal[- ]chave", r"equipa de projeto", r"gestor de projeto", r"curr[ií]culo",
        r"kl[ií][cč]ov[yý] person[aá]l", r"projektov[yý] mana[žz]er", r"k[ľl][uú][cč]ov[yý] person[aá]l",
    ],
    "insurance_bonds": [
        r"ubezpieczenie odpowiedzialno[śs]ci cywilnej", r"polisa ubezpieczeniowa", r"gwarancja bankowa", r"wadium",
        r"seguro de responsabilidad", r"garant[ií]a bancaria", r"garant[ií]a provisional",
        r"assicurazione di responsabilit[aà]", r"garanzia bancaria", r"cauzione",
        r"seguro de responsabilidade", r"garantia banc[aá]ria", r"cau[cç][aã]o",
        r"poji[šs]t[eě]n[ií] odpov[eě]dnosti", r"bankovn[ií] z[aá]ruka", r"poistenie zodpovednosti", r"bankov[aá] z[aá]ruka",
    ],
    "subcontracting_consortium": [
        r"podwykonawc", r"konsorcjum", r"wsp[oó]lne ubieganie", r"poleganie na zdolno[śs]ciach",
        r"subcontrataci[oó]n", r"uni[oó]n temporal", r"agrupaci[oó]n de operadores", r"capacidades de otras entidades",
        r"subappalto", r"raggruppamento temporaneo", r"avvalimento", r"consorzio",
        r"subcontrata[cç][aã]o", r"cons[oó]rcio", r"agrupamento", r"capacidades de outras entidades",
        r"poddodavatel", r"spole[cč]n[aá] nab[ií]dka", r"vyu[žz]it[ií] kapacit", r"subdod[aá]vate[ľl]", r"skupina dod[aá]vate[ľl]ov",
    ],
    "deliverables_scope": [
        r"opis przedmiotu zam[oó]wienia", r"zakres zam[oó]wienia", r"wymagania techniczne", r"rezultaty", r"produkty ko[nń]cowe",
        r"objeto del contrato", r"alcance de los trabajos", r"prescripciones t[eé]cnicas", r"entregables",
        r"oggetto dell'appalto", r"ambito delle prestazioni", r"specifiche tecniche", r"deliverable",
        r"objeto do contrato", r"[aâ]mbito dos trabalhos", r"especifica[cç][oõ]es t[eé]cnicas", r"entreg[aá]veis",
        r"p[řr]edm[eě]t zak[aá]zky", r"technick[eé] podm[ií]nky", r"predmet z[aá]kazky", r"technick[eé] po[žz]iadavky",
    ],
    "sla_onsite": [
        r"poziom [śs]wiadczenia us[łl]ug", r"czas reakcji", r"czas usuni[eę]cia", r"na miejscu", r"w siedzibie zamawiaj[aą]cego",
        r"nivel de servicio", r"tiempo de respuesta", r"presencial", r"in situ",
        r"livello di servizio", r"tempo di risposta", r"in presenza", r"presso la sede",
        r"n[ií]vel de servi[cç]o", r"tempo de resposta", r"presencial", r"no local",
        r"[uú]rove[nň] slu[žz]eb", r"doba odezvy", r"na m[ií]st[eě]", r"[uú]rove[nň] slu[žz]ieb", r"doba odozvy",
    ],
    "term_value": [
        r"okres obowi[aą]zywania umowy", r"czas trwania umowy", r"warto[śs][ćc] zam[oó]wienia", r"maksymalna warto[śs][ćc]", r"bud[żz]et",
        r"duraci[oó]n del contrato", r"valor estimado", r"presupuesto base", r"pr[oó]rroga",
        r"durata del contratto", r"valore stimato", r"importo massimo", r"proroga",
        r"dura[cç][aã]o do contrato", r"valor estimado", r"montante m[aá]ximo", r"prorroga[cç][aã]o",
        r"doba trv[aá]n[ií] smlouvy", r"p[řr]edpokl[aá]dan[aá] hodnota", r"doba trvania zmluvy", r"predpokladan[aá] hodnota",
    ],
    "award_criteria": [
        r"kryteria oceny ofert", r"kryteria udzielenia zam[oó]wienia", r"waga kryterium", r"punktacja",
        r"criterios de adjudicaci[oó]n", r"ponderaci[oó]n", r"puntuaci[oó]n m[ií]nima",
        r"criteri di aggiudicazione", r"ponderazione", r"punteggio minimo",
        r"crit[eé]rios de adjudica[cç][aã]o", r"pondera[cç][aã]o", r"pontua[cç][aã]o m[ií]nima",
        r"hodnot[ií]c[ií] krit[eé]ria", r"krit[eé]ri[aá] na vyhodnotenie pon[uú]k", r"v[aá]ha krit[eé]ria",
    ],
    "forms_signatures": [
        r"formularz ofertowy", r"obowi[aą]zkowy formularz", r"podpis kwalifikowany", r"o[śs]wiadczenie", r"pe[łl]nomocnictwo",
        r"formulario de oferta", r"formulario obligatorio", r"firma electr[oó]nica", r"declaraci[oó]n", r"poder de representaci[oó]n",
        r"modulo di offerta", r"firma digitale", r"dichiarazione", r"procura",
        r"formul[aá]rio da proposta", r"assinatura digital", r"declara[cç][aã]o", r"procura[cç][aã]o",
        r"nab[ií]dkov[yý] formul[aá][řr]", r"elektronick[yý] podpis", r"[cč]estn[eé] prohl[aá][šs]en[ií]", r"splnomocnenie",
    ],
    "submission": [
        r"termin sk[łl]adania ofert", r"termin z[łl]o[żz]enia ofert", r"spos[oó]b sk[łl]adania ofert", r"j[eę]zyk oferty", r"platforma zakupowa",
        r"plazo de presentaci[oó]n", r"fecha l[ií]mite", r"presentaci[oó]n electr[oó]nica", r"idioma de la oferta",
        r"termine (?:di )?presentazione", r"scadenza", r"presentazione telematica", r"lingua dell'offerta",
        r"prazo para apresenta[cç][aã]o", r"data limite", r"submiss[aã]o eletr[oó]nica", r"idioma da proposta",
        r"lh[uů]ta pro pod[aá]n[ií] nab[ií]dek", r"elektronick[eé] pod[aá]n[ií]", r"jazyk nab[ií]dky",
        r"lehota na predkladanie pon[uú]k", r"elektronick[eé] predkladanie", r"jazyk ponuky",
    ],
    "ip_data_security": [
        r"prawa autorskie", r"w[łl]asno[śs][ćc] intelektualna", r"ochrona danych osobowych", r"RODO", r"kod [źz]r[oó]d[łl]owy", r"bezpiecze[nń]stwo informacji",
        r"propiedad intelectual", r"derechos de autor", r"protecci[oó]n de datos", r"RGPD", r"c[oó]digo fuente", r"seguridad de la informaci[oó]n",
        r"propriet[aà] intellettuale", r"diritto d'autore", r"protezione dei dati", r"GDPR", r"codice sorgente", r"sicurezza delle informazioni",
        r"propriedade intelectual", r"direitos de autor", r"prote[cç][aã]o de dados", r"RGPD", r"c[oó]digo fonte", r"seguran[cç]a da informa[cç][aã]o",
        r"autorsk[eé] pr[aá]vo", r"ochrana osobn[ií]ch [uú]daj[uů]", r"zdrojov[yý] k[oó]d", r"informa[cč]n[ií] bezpe[cč]nost",
    ],
}

ALIASES = {
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


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def _snippets(text: str, patterns: list[str], window: int = 700, max_hits: int = 16) -> list[dict]:
    if not patterns:
        return []
    rx = re.compile("|".join(f"(?:{p})" for p in patterns), re.I | re.S)
    out = []
    seen = set()
    for m in rx.finditer(text or ""):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        snip = text[start:end].strip()
        key = re.sub(r"\s+", " ", snip[:260]).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "match": m.group(0)[:160],
            "start": start,
            "end": end,
            "snippet": snip,
            "retrieval_layer": "multilingual_rescue",
        })
        if len(out) >= max_hits:
            break
    return out


def _dedupe_merge(primary: list, rescue: list, limit: int = 28) -> list:
    out = []
    seen = set()
    for item in list(primary or []) + list(rescue or []):
        if not isinstance(item, dict):
            continue
        snip = str(item.get("snippet") or "")
        key = re.sub(r"\s+", " ", snip[:300]).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def process(root: Path) -> dict:
    evidence = _load(root / "evidence_quality.json", {})
    if not evidence.get("gate_readiness"):
        return {"candidate_root": str(root), "gate_readiness": False, "rescued": {}}
    corpus_path = root / "corpus.txt"
    if not corpus_path.exists():
        return {"candidate_root": str(root), "gate_readiness": True, "rescued": {}, "error": "corpus_missing"}

    text = corpus_path.read_text(encoding="utf-8", errors="replace")
    gate_path = root / "gate_snippets.json"
    gates = _load(gate_path, {})
    categories = gates.setdefault("categories", {})
    rescued_counts = {}

    for gate, patterns in EXTRA_PATTERNS.items():
        rescue = _snippets(text, patterns)
        before = categories.get(gate) or []
        merged = _dedupe_merge(before, rescue)
        categories[gate] = merged
        rescued_counts[gate] = max(0, len(merged) - len(before))

    # Refresh aliases to point at the merged canonical evidence lists.
    for alias, canonical in ALIASES.items():
        if canonical in categories:
            categories[alias] = categories[canonical]

    counts = gates.setdefault("evidence_counts", {})
    for key, items in categories.items():
        counts[key] = len(items) if isinstance(items, list) else 0
    gates["multilingual_rescue"] = {
        "applied": True,
        "rescued_counts": rescued_counts,
        "rescued_total": sum(rescued_counts.values()),
        "rule": "Recall rescue only. Added snippets remain evidence candidates and never imply a PASS.",
    }
    gate_path.write_text(json.dumps(gates, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "candidate_root": str(root),
        "gate_readiness": True,
        "rescued": rescued_counts,
        "rescued_total": sum(rescued_counts.values()),
    }
