#!/usr/bin/env python3
from __future__ import annotations

"""Apply manually audited SPM Micro-Niche v2 Precision evidence to LIVE priors.

This updater changes retrieval priority only. It never satisfies DCE gates and
never changes final bid/no-bid eligibility semantics.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def rule(lane, country, sample_size, score, bonus, decision, patterns, negative_patterns=(), match_field="title"):
    return {
        "lane": lane,
        "country": country,
        "sample_size": sample_size,
        "historical_score": score,
        "priority_bonus": bonus,
        "decision": decision,
        "match_field": match_field,
        "patterns": list(patterns),
        "negative_patterns": list(negative_patterns),
    }


def upsert(rules: list[dict], new: dict, aliases: tuple[str, ...] = ()):
    names = {new["lane"], *aliases}
    for i, old in enumerate(rules):
        if old.get("country", "") == new.get("country", "") and old.get("lane") in names:
            rules[i] = new
            return
    rules.append(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--priors", default="control/historical_market_priors.json")
    ap.add_argument("--out", default="control/historical_market_priors.json")
    a = ap.parse_args()
    data = json.loads(Path(a.priors).read_text(encoding="utf-8"))
    if data.get("contract") != "TENDER_MARKET_BRAIN_PRIORS_V1" or data.get("status") != "READY":
        raise SystemExit("historical priors are not READY TENDER_MARKET_BRAIN_PRIORS_V1")
    rules = list(data.get("lane_rules") or [])

    # France print + routing: strong recurring broker lane. Tight title-led regexes
    # prevent printer/copier hardware and premises-conversion false positives.
    upsert(rules, rule(
        "Printing / mailing / routing", "FRANCE", 779, 84.90, 6, "PROMOTE_BROKER",
        [
            r"travaux d['’]impression", r"prestations? d['’]impression", r"services? d['’]impression",
            r"\bimpression (?:de|des|et)\b", r"\broutage\b", r"mise sous pli", r"\bmailing\b",
        ],
        [
            r"3d print", r"printer maintenance", r"\bimprimante", r"\bcopieur", r"managed print",
            r"syst[eè]me.{0,30}impression", r"presse num[eé]rique", r"location.{0,30}(?:presse|copieur)",
            r"maintenance.{0,30}(?:presse|copieur)", r"transformation.{0,40}imprimerie",
        ],
    ))

    upsert(rules, rule(
        "Graphic design / layout / DTP", "FRANCE", 194, 85.97, 6, "PROMOTE_CORE",
        [r"conception graphique", r"design graphique", r"\bgraphisme\b", r"mise en page", r"identit[eé] visuelle", r"desktop publishing", r"\binfograph"],
        [r"architect", r"engineering", r"ma[iî]trise d['’]oeuvre", r"construction", r"sc[eé]nograph", r"mus[eé]ograph", r"exposition", r"\btravaux\b", r"\bstand\b"],
    ), aliases=("Graphic design / DTP / visual identity",))

    upsert(rules, rule(
        "Translation", "FRANCE", 139, 84.28, 5, "PROMOTE_CORE",
        [r"\btraduction\b", r"\binterpr[eé]tariat\b", r"translation services?", r"linguistic translation"],
        [r"translational", r"translationnelle", r"m[eé]decine", r"mat[eé]riel.{0,40}traduction", r"audiovisuel.{0,50}traduction", r"translation.{0,40}equipment"],
    ), aliases=("Translation services",))

    upsert(rules, rule(
        "Transcription / speech-to-text", "FRANCE", 58, 82.42, 4, "PROMOTE_CORE",
        [r"\btranscription\b", r"\bretranscription\b", r"st[eé]notyp", r"speech[- ]to[- ]text"],
        [r"dna transcription", r"gene transcription", r"transcription factor"],
    ))

    # Germany web support: explicitly require a web noun and support/maintenance
    # noun within one title. Both word orders are allowed.
    upsert(rules, rule(
        "Website support / accessibility / hosting", "GERMANY", 90, 86.29, 5, "PROMOTE_CORE",
        [
            r"(?:webseite|website|internetauftritt|webauftritt).{0,90}(?:pflege|wartung|betreuung|support|hosting|betrieb)",
            r"(?:pflege|wartung|betreuung|support|hosting|betrieb).{0,90}(?:webseite|website|internetauftritt|webauftritt)",
        ],
        [r"construction", r"hardware", r"security portal", r"portal crane"],
    ))

    upsert(rules, rule(
        "Website support / accessibility / hosting", "FRANCE", 121, 81.97, 5, "PROMOTE_CORE",
        [
            r"(?:site web|site internet|website|portail web).{0,90}(?:maintenance|support|h[eé]bergement|entretien|mise [àa] jour)",
            r"(?:maintenance|support|h[eé]bergement|entretien|mise [àa] jour).{0,90}(?:site web|site internet|website|portail web)",
        ],
        [r"construction", r"hardware", r"security portal", r"x-ray"],
    ))

    upsert(rules, rule(
        "Website / CMS build or redesign", "FRANCE", 66, 79.14, 4, "PROMOTE_CORE",
        [
            r"(?:refonte|cr[eé]ation|conception|d[eé]veloppement|relaunch|redesign).{0,90}(?:site internet|site web|website|portail web)",
            r"(?:site internet|site web|website|portail web).{0,90}(?:refonte|cr[eé]ation|conception|d[eé]veloppement|relaunch|redesign)",
            r"(?:wordpress|drupal|joomla).{0,90}(?:site|website|cms|portail)",
        ],
        [r"portal crane", r"security portal", r"x-ray", r"medical", r"construction", r"hardware"],
    ))

    # Legacy v9 web-build priors remain useful, but v1 QA proved that broad scope
    # matching could contaminate them. Preserve their old evidence/weight while
    # forcing title-led explicit build/redesign semantics.
    upsert(rules, rule(
        "Website / CMS build or redesign", "GERMANY", 230, 81.36, 5, "PROMOTE_CORE",
        [
            r"(?:relaunch|neugestaltung|entwicklung|redesign).{0,90}(?:webseite|website|internetauftritt|webportal)",
            r"(?:webseite|website|internetauftritt|webportal).{0,90}(?:relaunch|neugestaltung|entwicklung|redesign)",
            r"(?:wordpress|drupal|joomla).{0,90}(?:webseite|website|cms|portal)",
        ],
        [r"portal crane", r"security portal", r"x-ray", r"medical", r"construction", r"hardware supply"],
    ))

    upsert(rules, rule(
        "Website / CMS build or redesign", "UNITED KINGDOM", 60, 70.10, 3, "PROMOTE_CORE",
        [
            r"(?:redesign|rebuild|development|develop|new website).{0,90}(?:website|web site|web portal|cms)",
            r"(?:website|web site|web portal|cms).{0,90}(?:redesign|rebuild|development|develop)",
            r"(?:wordpress|drupal|joomla).{0,90}(?:website|cms|portal)",
        ],
        [r"portal crane", r"security portal", r"x-ray", r"medical", r"construction", r"hardware"],
    ))

    upsert(rules, rule(
        "Website support / accessibility / hosting", "IRELAND", 53, 66.57, 3, "PROMOTE_CORE",
        [
            r"(?:website|web site|web portal).{0,90}(?:maintenance|support|hosting|accessibil)",
            r"(?:maintenance|support|hosting|accessibil).{0,90}(?:website|web site|web portal)",
        ],
        [r"construction", r"hardware"],
    ))

    upsert(rules, rule(
        "Commercial printing / print production", "CANADA - QUEBEC", 68, 90.86, 5, "PROMOTE_BROKER",
        [r"services? d['’]impression", r"travaux d['’]impression", r"\bimpression (?:de|des|pour)\b", r"communications? imprim[eé]es?", r"impression grand format"],
        [r"\bimprimante", r"\bcopieur", r"managed print", r"3d print", r"maintenance.{0,30}(?:imprimante|copieur)", r"location.{0,30}(?:imprimante|copieur)"],
    ))

    upsert(rules, rule(
        "Translation", "CANADA", 35, 81.50, 3, "PROMOTE_CORE",
        [r"translation services?", r"professional translation", r"technical translation", r"sign language translation", r"interpretation services?"],
        [r"translational", r"translation.{0,40}equipment", r"simultaneous interpretation equipment"],
    ))

    # Previously broad Ireland survey rule was quantitatively attractive but
    # sample QA still contained archaeological survey work. Keep the evidence but
    # fail closed: loader ignores decisions outside PROMOTE_*.
    upsert(rules, rule(
        "Survey / market research", "IRELAND", 30, 86.48, 0, "HOLD_QA",
        [r"market research", r"opinion poll", r"customer survey", r"satisfaction survey", r"research panel"],
        [r"archaeolog", r"topograph", r"lidar", r"ornitholog", r"ecolog", r"geotechn", r"soil", r"drilling", r"borehole"],
    ))

    data["lane_rules"] = rules
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    data["source_release"] = "walidgdg1-ai/tender-engine:market-intelligence-v9-final-qa + market-intelligence-micro-niche-v2-precision"
    data["source_scope"] = "Global Core v4 notice-first. v9 cleaned lanes plus title-led Micro-Niche v2 Precision lanes admitted only after persisted manual QA. Direct/noncompetitive evidence remains buyer-demand intelligence only."
    data["micro_niche_precision_v2"] = {
        "authority": "control/micro_niche_intelligence_v2_precision/MANUAL_PROMOTION_VERDICT.md",
        "source_release": "market-intelligence-micro-niche-v2-precision",
        "classified_notice_first_tenders": 7427,
        "micro_niches": 23,
        "promoted_or_strengthened": [
            "Quebec commercial printing",
            "Germany website maintenance/hosting/support",
            "France graphic design/layout/DTP",
            "France printing/mailing/routing",
            "France translation",
            "France transcription/speech-to-text",
            "France website maintenance/hosting/support",
            "France website build/redesign",
            "Canada federal translation (modest)",
        ],
        "legacy_rules_hardened_title_led": [
            "Germany website/CMS build",
            "United Kingdom website/CMS build",
            "Ireland website support/hosting",
        ],
        "held": [
            "Ireland broad survey/market research (semantic QA)",
            "Quebec market research (delivery-model QA)",
            "Ireland media monitoring (winner concentration)",
        ],
        "title_led": True,
        "note": "Only PROMOTE_CORE/PROMOTE_BROKER rules can affect live retrieval. HOLD_* rules are persisted for audit but ignored by the loader.",
    }
    Path(a.out).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
