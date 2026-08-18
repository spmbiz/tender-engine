from __future__ import annotations

"""Deterministic procurement-code priors for scheduling only.

These signals NEVER decide eligibility, never mark a notice DROP, and never replace
Qwen or authoritative DCE review. They only alter which already-Qwen-classified
notice gets DCE capacity first.

CPV mappings are based on the official TED CPV tree. NAICS mappings mirror the
existing high-recall fast lane in auto_select_dce.py.
"""

import re
from typing import Any

# Strong positive families already used by the established lexical DCE lane.
CPV_POSITIVE_PREFIXES: tuple[tuple[str, str, int], ...] = (
    ("72413", "SPM_WEB", 18),        # World wide web site design services
    ("72415", "SPM_WEB", 16),        # WWW site operation host services
    ("7242", "SPM_WEB", 15),         # Internet development services
    ("724", "SPM_WEB", 10),
    ("7223", "SPM_SOFTWARE", 16),    # Custom software development
    ("72212", "SPM_SOFTWARE", 16),   # Application software programming/development
    ("722", "SPM_SOFTWARE", 12),
    ("723122", "SPM_OCR", 17),       # Optical character recognition services
    ("72312", "SPM_DATA", 12),       # Data entry/preparation
    ("723", "SPM_DATA", 8),
    ("798", "SPM_PRINT", 16),
    ("9211", "SPM_VIDEO", 16),
    ("7934", "SPM_MARKETING", 14),
    ("7953", "SPM_TRANSLATION_TRANSCRIPTION", 14),
    ("805", "SPM_TRAINING", 7),
)

NAICS_POSITIVE_PREFIXES: tuple[tuple[str, str, int], ...] = (
    ("541511", "SPM_SOFTWARE", 16),
    ("541512", "SPM_SOFTWARE", 15),
    ("541513", "SPM_IT", 10),
    ("541519", "SPM_IT", 10),
    ("518210", "SPM_IT", 10),
    ("541430", "SPM_DESIGN", 16),
    ("541810", "SPM_MARKETING", 14),
    ("512110", "SPM_VIDEO", 15),
    ("512191", "SPM_VIDEO", 14),
    ("561410", "SPM_TRANSCRIPTION", 12),
    ("323111", "SPM_PRINT", 15),
    ("323113", "SPM_PRINT", 14),
    ("611420", "SPM_TRAINING", 10),
)

# Official CPV divisions that are strongly outside SPM's lean digital/creative
# core. This is only a bounded scheduling demotion. The notice stays KEEP/DCE-
# eligible and can still be explored if Qwen sees a real mixed/digital opportunity.
CPV_NONCORE_DIVISIONS: dict[str, str] = {
    "33": "medical-pharma-personal-care",
    "34": "transport-equipment",
    "42": "industrial-machinery",
    "44": "construction-materials",
    "45": "construction-work",
    "50": "repair-maintenance-nondigital",
    "90": "sewage-refuse-cleaning-environmental",
}


def _flatten(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def _sources(rec: dict[str, Any], names: tuple[str, ...]) -> str:
    chunks: list[str] = []
    notice = rec.get("notice") if isinstance(rec.get("notice"), dict) else {}
    for src in (rec, notice):
        for name in names:
            if name in src:
                chunks.append(_flatten(src.get(name)))
    return " ".join(chunks)


def cpv_tokens(rec: dict[str, Any]) -> list[str]:
    raw = _sources(rec, ("cpv", "cpv_codes", "cpv_or_category", "category", "categories", "classification"))
    return sorted(set(re.findall(r"(?<!\d)(\d{5,8})(?!\d)", raw)))


def naics_tokens(rec: dict[str, Any]) -> list[str]:
    raw = _sources(rec, ("naics", "naics_code", "naics_codes", "classification", "category"))
    return sorted(set(re.findall(r"(?<!\d)(\d{5,6})(?!\d)", raw)))


def code_priority(rec: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded additive priority signal; never eligibility truth."""
    cpvs = cpv_tokens(rec)
    naics = naics_tokens(rec)
    positive: list[str] = []
    negative: list[str] = []
    boost = 0

    for code in cpvs:
        for prefix, family, pts in CPV_POSITIVE_PREFIXES:
            if code.startswith(prefix):
                boost = max(boost, pts)
                positive.append(f"cpv:{code}:{family}")
                break

    for code in naics:
        for prefix, family, pts in NAICS_POSITIVE_PREFIXES:
            if code.startswith(prefix):
                boost = max(boost, pts)
                positive.append(f"naics:{code}:{family}")
                break

    # A positive digital/creative code always wins over a broad non-core division;
    # mixed procurements must stay high-recall.
    penalty = 0
    if not positive:
        for code in cpvs:
            label = CPV_NONCORE_DIVISIONS.get(code[:2])
            if label:
                negative.append(f"cpv:{code}:{label}")
        if negative:
            penalty = -20

    delta = max(-20, min(18, boost + penalty))
    return {
        "delta": delta,
        "positive": sorted(set(positive)),
        "negative": sorted(set(negative)),
        "cpv_tokens": cpvs,
        "naics_tokens": naics,
        "contradiction": bool(negative and not positive),
        "rule": "priority_only_never_drop_never_eligibility",
    }
