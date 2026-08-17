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


def scope_text(row: Mapping[str, Any]) -> str:
    """Return scope-only text; avoid unrelated submission/security evidence."""
    parts = [
        str(_first(row, "title") or ""),
        str(_first(row, "description", "summary", "description_excerpt") or ""),
    ]
    evidence = _evidence_map(row)
    deliverables = evidence.get("deliverables_scope") if isinstance(evidence, Mapping) else None
    if isinstance(deliverables, (list, tuple)):
        parts.extend(_item_text(item) for item in deliverables[:6])
    elif deliverables:
        parts.append(_item_text(deliverables))
    return " ".join(" ".join(parts).split())[:16000]


def evaluate_post_dce_scope(row: Mapping[str, Any]) -> dict[str, Any]:
    """Conservatively auto-reject only unambiguous non-broker physical scopes."""
    text = scope_text(row)
    if not text:
        return {"auto_reject": False, "reason_codes": [], "matched_patterns": [], "digital_override": False}

    # A substantive digital-native scope always survives to GPT. Deliberately omit broad
    # words such as "design", "portal", "automation", and "content" to avoid false overrides.
    if _DIGITAL_NATIVE.search(text):
        return {"auto_reject": False, "reason_codes": [], "matched_patterns": [], "digital_override": True}

    reasons: list[str] = []
    matches: list[str] = []
    for reason, pattern in _HARD_SCOPE_RULES:
        match = pattern.search(text)
        if match:
            reasons.append(reason)
            matches.append(" ".join(match.group(0).split())[:220])

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
