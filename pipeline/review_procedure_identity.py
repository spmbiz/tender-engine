from __future__ import annotations

import re
from typing import Any

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ie_resource", re.compile(r"(?:resourceId|resourceid)[=/](\d{5,})", re.I)),
    ("ie_resource", re.compile(r"[?&]resourceId=(\d{5,})", re.I)),
    ("ocds", re.compile(r"\b(ocds-[a-z0-9-]{8,})\b", re.I)),
    ("sam_opp", re.compile(r"sam\.gov/opp/([a-f0-9]{20,})", re.I)),
    ("dtvp_notice", re.compile(r"(?:notice/|project/)(CXS[A-Z0-9]{8,})", re.I)),
)


def _flatten(value: Any):
    if value in (None, ""):
        return
    if isinstance(value, dict):
        for v in value.values():
            yield from _flatten(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _flatten(v)
    else:
        yield str(value)


def strong_procedure_aliases(row: dict[str, Any]) -> list[str]:
    """Return only explicit stable procedure aliases present in source evidence.

    No title similarity, buyer similarity, CPV or deadline inference is used here.
    The goal is safe cross-portal dedupe, never entity resolution by guesswork.
    """
    values: list[str] = []
    for key in (
        "notice_url", "source_url", "source_urls", "retrieved_url",
        "artifact_locator", "evidence_quality", "evidence_quality_summary",
        "candidate_id",
    ):
        values.extend(_flatten(row.get(key)) or [])

    out: set[str] = set()
    for text in values:
        for kind, rx in _PATTERNS:
            for m in rx.finditer(text):
                token = m.group(1).strip().casefold()
                if token:
                    out.add(f"{kind}:{token}")
    return sorted(out)


def canonical_review_key(row: dict[str, Any]) -> str:
    aliases = strong_procedure_aliases(row)
    if aliases:
        # Prefer eTenders/OCDS/DTVP aliases because they often join a TED mirror to
        # the authoritative national procedure. Any common alias dedupes later.
        order = {"ie_resource": 0, "ocds": 1, "dtvp_notice": 2, "sam_opp": 3}
        aliases.sort(key=lambda x: (order.get(x.split(":", 1)[0], 99), x))
        return aliases[0]
    return "candidate:" + str(row.get("candidate_id") or "").strip().casefold()


def shared_alias(a: dict[str, Any], b: dict[str, Any]) -> bool:
    aa = set(strong_procedure_aliases(a))
    bb = set(strong_procedure_aliases(b))
    return bool(aa and bb and aa.intersection(bb))


def review_row_quality(row: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    quality = str(row.get("content_quality") or "").upper()
    deadline_status = str(row.get("deadline_authority_status") or "").upper()
    deadline_resolved = bool(row.get("deadline_resolved")) or (
        "AUTHORITATIVE_SUBMISSION" in deadline_status or "RESOLVED" in deadline_status
    )
    substantive = quality in {"SUBSTANTIVE_DCE_PRESENT", "MIXED_SUBSTANTIVE_AND_GUIDE"}
    return (
        int(deadline_resolved),
        int(bool(row.get("gate_readiness"))),
        int(substantive),
        int(row.get("evidence_gate_coverage") or 0),
        int(row.get("source_dce_run_id") or 0),
        str(row.get("candidate_id") or ""),
    )
