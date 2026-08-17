from __future__ import annotations

import re
from typing import Any, Mapping


# This gate is intentionally conservative. Qwen remains the high-recall semantic sieve;
# deterministic rejection happens only after DCE recovery and only for scopes that are
# unambiguously physical works/services outside SPM's lean execution model.
# Commodity/supply opportunities remain reviewable because they may be brokerable.

_DIGITAL_NATIVE = re.compile(
    r"\b(?:"
    r"websites?|web[ -]?apps?|web applications?|web development|web redesign|webar|"
    r"software|saas|cloud services?|content management systems?|cms|"
    r"mobile apps?|application development|software development|"
    r"digital services?|digitisation|digitization|digitalisierung|"
    r"graphic design|branding|brand identity|animation|audiovisual|video production|film production|"
    r"social media|digital marketing|translation|transcription|copywriting|proofreading|"
    r"e-learning|online training|training content|data processing|data entry|document scanning|"
    r"cybersecurity|information technology|it services?|artificial intelligence|machine learning|"
    r"augmented reality|virtual reality|qr codes?|"
    r"building automation software|bas analytics|controls analytics"
    r")\b",
    re.I,
)

# These phrases are strong enough to prove that a digital component is subordinate to a
# physical construction/installation contract. They are evaluated BEFORE the digital
# override. This prevents a huge facility build from surviving merely because its DCE
# contains e.g. cybersecurity, audiovisual, or software configuration requirements.
_DOMINANT_PHYSICAL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "NO_SCOPE_DOMINANT_PHYSICAL_STRAIGHT_TO_CONSTRUCTION",
        re.compile(r"\bstraight[ -]?to[ -]?construction\b", re.I),
    ),
    (
        "NO_SCOPE_DOMINANT_PHYSICAL_FACILITY_CONSTRUCTION",
        re.compile(
            r"(?:\b(?:construct|construction of|new construction|facility construction|building construction)\b"
            r".{0,120}\b(?:building|facility|courthouse|clinic|station|hangar|warehouse)\b|"
            r"\b(?:building|facility|courthouse|clinic|station|hangar|warehouse)\b"
            r".{0,120}\b(?:construction project|construction works?|new construction)\b)",
            re.I,
        ),
    ),
    (
        "NO_SCOPE_DOMINANT_PHYSICAL_TURNKEY_INSTALLATION",
        re.compile(
            r"\bprovide all labor, materials, equipment, supervision(?:,? and incidentals)?\b"
            r".{0,180}\b(?:furnish and install|design and install|construct)\b"
            r".{0,180}\b(?:building automation system|bas|generator|hvac|heating|ventilation|"
            r"air conditioning|electrical system|mechanical system|facility equipment)\b",
            re.I,
        ),
    ),
)

# Major prime-construction contracts are sometimes described by a generic project title
# while their deliverables snippets contain digital subcomponents. In those cases, use
# multiple independent commercial/execution signals from narrowly selected DCE gates.
# One marker is never enough: requiring >=2 avoids killing a digital subcontract merely
# because it says "coordinate with the construction contractor".
_PRIME_CONSTRUCTION_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "construction_superintendent",
        re.compile(
            r"(?:\bproject superintendent\b.{0,180}\bconstruction\b|"
            r"\bconstruction\b.{0,180}\bproject superintendent\b)",
            re.I,
        ),
    ),
    (
        "fixed_price_construction_contract",
        re.compile(r"\bFAR\s*52\.232-5\b.{0,100}\bFixed-Price Construction Contracts?\b", re.I),
    ),
    (
        "builders_risk",
        re.compile(r"\bBuilder'?s Risk Insurance\b", re.I),
    ),
    (
        "performance_bond_100pct",
        re.compile(r"\bPerformance Bond\b.{0,100}\b100\s*(?:percent|%)\b", re.I),
    ),
    (
        "construction_prime_staff",
        re.compile(
            r"\b(?:Project Manager|Superintendent)\b.{0,220}\b(?:Site Safety and Health Officer|SSHO|Quality Control Manager)\b",
            re.I,
        ),
    ),
    (
        "construction_contractor",
        re.compile(r"\bConstruction Contractor\b", re.I),
    ),
)

_HARD_SCOPE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "NO_SCOPE_PHYSICAL_HVAC_WORKS",
        re.compile(
            r"(?:\b(?:replace|replacement|repair|maintenance|install(?:ation|ing)?|upgrade|moderni[sz](?:e|ation)|retrofit(?:ting)?)\b.{0,80}\b(?:hvac|heating|ventilation|air conditioning|chiller)\b|"
            r"\b(?:hvac|heating|ventilation|air conditioning|chiller)\b.{0,80}\b(?:replace|replacement|repair|maintenance|install(?:ation|ing)?|upgrade|moderni[sz](?:e|ation)|retrofit(?:ting)?)\b)",
            re.I,
        ),
    ),
    (
        "NO_SCOPE_PHYSICAL_CONSTRUCTION_WORKS",
        re.compile(
            r"\b(?:construction works?|civil works?|building construction|courthouse construction|"
            r"building renovations?|renovation works?|site works?|painting works?|electrical works?)\b",
            re.I,
        ),
    ),
    (
        "NO_SCOPE_PHYSICAL_DESIGN_BUILD_INFRASTRUCTURE",
        re.compile(
            r"\bdesign[ -]?build\b.{0,140}\b(?:building|facility|facilities|road|bridge|water supply|"
            r"storage system|pipeline|utility|utilities|infrastructure|plant|station|site)\b|"
            r"\b(?:building|facility|facilities|road|bridge|water supply|storage system|pipeline|utility|"
            r"utilities|infrastructure|plant|station|site)\b.{0,140}\bdesign[ -]?build\b",
            re.I,
        ),
    ),
    (
        "NO_SCOPE_PHYSICAL_ROAD_BRIDGE_WORKS",
        re.compile(
            r"\b(?:asphalt paving|paving works?|road works?|road rehabilitation|bridge repair|"
            r"bridge rehabilitation|bridge replacement)\b",
            re.I,
        ),
    ),
    (
        "NO_SCOPE_PHYSICAL_DREDGING",
        re.compile(r"\b(?:dredging|dredge works?|dredging and sediment disposal)\b", re.I),
    ),
    (
        "NO_SCOPE_PHYSICAL_ROOFING_WORKS",
        re.compile(r"\b(?:roof replacement|roofing works?|replace (?:the )?roof|roof repair)\b", re.I),
    ),
    (
        "NO_SCOPE_PHYSICAL_WASTE_SERVICE",
        re.compile(r"\b(?:waste removal|solid waste collection|refuse collection|garbage collection)\b", re.I),
    ),
    (
        "NO_SCOPE_PHYSICAL_STEAM_CONDENSATE_WORKS",
        re.compile(
            r"(?:\b(?:repair|replace|replacement|install(?:ation|ing)?|maintenance)\b.{0,80}\b(?:steam|condensate)\b|"
            r"\b(?:steam|condensate)\b.{0,80}\b(?:repair|replace|replacement|install(?:ation|ing)?|maintenance)\b)",
            re.I,
        ),
    ),
)


def _candidate(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("candidate")
    return value if isinstance(value, Mapping) else {}


def _first(row: Mapping[str, Any], *names: str) -> Any:
    candidate = _candidate(row)
    for source in (row, candidate):
        for name in names:
            value = source.get(name)
            if value not in (None, "", [], {}):
                return value
    return None


def _evidence_map(row: Mapping[str, Any]) -> Mapping[str, Any]:
    snippets = (
        row.get("gate_snippets")
        or row.get("evidence_by_gate")
        or row.get("gate_evidence_candidates")
        or {}
    )
    if not isinstance(snippets, Mapping):
        return {}
    for nested_key in ("categories", "gate_evidence", "evidence_by_gate", "gate_evidence_candidates"):
        nested = snippets.get(nested_key)
        if isinstance(nested, Mapping):
            return nested
    return snippets


def _item_text(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("text") or item.get("snippet") or item.get("evidence") or "")
    return str(item or "")


def _gate_text(evidence: Mapping[str, Any], gate: str, limit: int = 6) -> str:
    value = evidence.get(gate)
    if isinstance(value, (list, tuple)):
        return " ".join(_item_text(item) for item in value[:limit])
    return _item_text(value) if value else ""


def scope_text(row: Mapping[str, Any]) -> str:
    """Return scope-only text; avoid unrelated submission/security evidence."""
    parts = [
        str(_first(row, "title") or ""),
        str(_first(row, "description", "summary", "description_excerpt") or ""),
    ]
    evidence = _evidence_map(row)
    parts.append(_gate_text(evidence, "deliverables_scope"))
    return " ".join(" ".join(parts).split())[:16000]


def prime_construction_evidence_text(row: Mapping[str, Any]) -> str:
    """Narrow evidence surface for proving a candidate is the construction prime."""
    evidence = _evidence_map(row)
    parts = [scope_text(row)]
    for gate in ("staffing_team", "insurance_bonds", "subcontracting_consortium"):
        parts.append(_gate_text(evidence, gate, limit=4))
    return " ".join(" ".join(parts).split())[:30000]


def _matches(rules: tuple[tuple[str, re.Pattern[str]], ...], text: str) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    matches: list[str] = []
    for reason, pattern in rules:
        match = pattern.search(text)
        if match:
            reasons.append(reason)
            matches.append(" ".join(match.group(0).split())[:220])
    return reasons, matches


def _prime_construction_markers(row: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    text = prime_construction_evidence_text(row)
    names: list[str] = []
    matches: list[str] = []
    for name, pattern in _PRIME_CONSTRUCTION_MARKERS:
        match = pattern.search(text)
        if match:
            names.append(name)
            matches.append(" ".join(match.group(0).split())[:220])
    return names, matches


def evaluate_post_dce_scope(row: Mapping[str, Any]) -> dict[str, Any]:
    """Conservatively auto-reject only unambiguous non-broker physical scopes."""
    text = scope_text(row)
    if not text:
        return {"auto_reject": False, "reason_codes": [], "matched_patterns": [], "digital_override": False}

    dominant_reasons, dominant_matches = _matches(_DOMINANT_PHYSICAL_RULES, text)
    if dominant_reasons:
        return {
            "auto_reject": True,
            "reason_codes": dominant_reasons,
            "matched_patterns": dominant_matches,
            "digital_override": False,
        }

    prime_markers, prime_matches = _prime_construction_markers(row)
    if len(prime_markers) >= 2:
        return {
            "auto_reject": True,
            "reason_codes": ["NO_SCOPE_DOMINANT_PHYSICAL_PRIME_CONSTRUCTION"],
            "matched_patterns": [f"{name}: {match}" for name, match in zip(prime_markers, prime_matches)],
            "digital_override": False,
        }

    # A substantive digital-native scope survives ordinary physical keyword matches.
    # Deliberately omit broad words such as "design", "portal", "automation", and
    # "content" to avoid false overrides. Dominant construction evidence above wins.
    if _DIGITAL_NATIVE.search(text):
        return {"auto_reject": False, "reason_codes": [], "matched_patterns": [], "digital_override": True}

    reasons, matches = _matches(_HARD_SCOPE_RULES, text)
    return {
        "auto_reject": bool(reasons),
        "reason_codes": reasons,
        "matched_patterns": matches,
        "digital_override": False,
    }


def scope_reject_audit(row: Mapping[str, Any], result: Mapping[str, Any], run_id: Any, timestamp: str) -> dict[str, Any]:
    return {
        "candidate_id": _first(row, "candidate_id"),
        "title": _first(row, "title"),
        "buyer": _first(row, "buyer", "contracting_authority"),
        "notice_url": _first(row, "notice_url", "source_url", "url"),
        "scope_reject_reason_codes": list(result.get("reason_codes") or []),
        "scope_reject_matches": list(result.get("matched_patterns") or []),
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "auto_rejected_at": timestamp,
    }
