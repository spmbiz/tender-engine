from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from build_gpt_review_backlog import item_key, portfolio_select

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "public", "service",
    "services", "supply", "supplies", "contract", "tender", "procurement", "request",
    "proposal", "solicitation", "notice", "digital", "online", "support", "provision",
    "development", "system", "systems", "project", "framework", "agreement", "management",
}

# Attention penalties only. They never delete a notice from discovery or a durable DCE pack.
FRICTION_RULES: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (re.compile(r"\b(?:sdvosb|service[- ]disabl(?:ed|e) veteran[- ]owned small business)\b", re.I), -85, "us-sdvosb-set-aside"),
    (re.compile(r"\b(?:vosb|veteran[- ]owned small business)\b", re.I), -60, "us-vosb-set-aside"),
    (re.compile(r"\b(?:wosb|women[- ]owned small business)\b", re.I), -55, "us-wosb-set-aside"),
    (re.compile(r"\b(?:edwosb|economically disadvantaged women[- ]owned small business)\b", re.I), -55, "us-edwosb-set-aside"),
    (re.compile(r"\bhubzone\b", re.I), -55, "us-hubzone-set-aside"),
    (re.compile(r"\b8\s*\(a\)(?:\s|$)", re.I), -65, "us-8a-set-aside"),
    (re.compile(r"\b(?:direct|sole[- ]source)[^.]{0,140}\b8\s*\(a\)", re.I), -85, "us-direct-8a-award"),
    (re.compile(r"\b(?:100\s*%\s*)?(?:total\s+)?small business set[- ]aside\b", re.I), -45, "us-small-business-set-aside"),
    (re.compile(r"\b(?:all\s+)?(?:contractor\s+)?(?:personnel|employees|staff)(?:[^.]{0,100})?(?:shall|must|required to)\s+be\s+u\.?s\.?\s+citizens?\b", re.I), -90, "us-citizens-only"),
    (re.compile(r"\b(?:shall|must|required to)\s+be\s+u\.?s\.?\s+citizens?\b", re.I), -80, "us-citizens-only"),
    (re.compile(r"\bu\.?s\.?\s+citizens?\s+only\b", re.I), -80, "us-citizens-only"),
    (re.compile(r"\btop\s+secret\b", re.I), -75, "top-secret-clearance"),
    (re.compile(r"\bsci\s+eligible\b", re.I), -65, "sci-eligibility"),
    (re.compile(r"\bsecurity clearance\b", re.I), -45, "security-clearance"),
    (re.compile(r"\bno award will be made\b", re.I), -70, "rfi-no-award"),
    (re.compile(r"\bnot (?:a|an) (?:request for proposal|solicitation)\b", re.I), -55, "not-an-award-solicitation"),
    (re.compile(r"\bdoes not constitute (?:a|an) (?:request for proposals?|request for quotations?|invitation for bids?|solicitation)\b", re.I), -70, "market-research-not-solicitation"),
    (re.compile(r"\bsources sought\b", re.I), -45, "sources-sought"),
    (re.compile(r"\bmarket research(?: purposes)? only\b", re.I), -45, "market-research-only"),
    (re.compile(r"\blive,?\s+open\s+surgery\b", re.I), -55, "specialist-live-surgery-production"),
    (re.compile(r"\bin[- ]person court reporting\b", re.I), -35, "in-person-court-reporting"),
)


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def evidence_text(row: dict[str, Any]) -> str:
    chunks: list[str] = []
    evidence = row.get("evidence_by_gate") or {}
    if isinstance(evidence, dict):
        for values in evidence.values():
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, dict):
                    chunks.append(str(value.get("text") or value.get("snippet") or value.get("context") or ""))
                elif isinstance(value, str):
                    chunks.append(value)
    return " ".join(chunks)


def legacy_relevance(row: dict[str, Any]) -> dict[str, Any]:
    """Prove legacy rows only from candidate-specific title evidence already in the DCE pack."""
    title = str(row.get("title") or "").strip()
    title_norm = norm(title)
    corpus_norm = norm(evidence_text(row))
    if title_norm and len(title_norm) >= 10 and title_norm in corpus_norm:
        return {"status": "PROVEN_BY_BACKFILL_TITLE_PHRASE", "proven": True}

    tokens = sorted({t for t in re.findall(r"[a-z0-9]{4,}", title_norm) if t not in STOPWORDS})
    hits = [t for t in tokens if re.search(rf"\b{re.escape(t)}\b", corpus_norm)]
    ratio = len(hits) / len(tokens) if tokens else 0.0
    if len(hits) >= 2 and ratio >= 0.5:
        return {
            "status": "PROVEN_BY_BACKFILL_TITLE_TOKENS",
            "proven": True,
            "title_token_hits": hits[:20],
            "title_token_ratio": round(ratio, 4),
        }
    return {
        "status": "UNPROVEN_LEGACY_CANDIDATE_DOCUMENT_MATCH",
        "proven": False,
        "title_token_hits": hits[:20],
        "title_token_ratio": round(ratio, 4),
    }


def band(score: int) -> str:
    if score >= 65:
        return "HOT"
    if score >= 40:
        return "GOOD"
    if score >= 20:
        return "MAYBE"
    return "LOW"


def apply_deadline_attention(row: dict[str, Any], score: int, blockers: list[str], applied: set[str]) -> int:
    """Unresolved dates stay reviewable, but cannot outrank a current, reconciled DCE."""
    if bool(row.get("deadline_resolved")):
        return score
    status = str(row.get("deadline_authority_status") or "").upper()
    if "CONFLICT" in status:
        if "deadline-conflict" not in applied:
            score -= 25
            blockers.append("deadline-conflict")
            applied.add("deadline-conflict")
        return min(score, 39)  # MAYBE until authority is reconciled.
    if "UNKNOWN" in status or not status:
        if "deadline-unresolved" not in applied:
            score -= 10
            blockers.append("deadline-unresolved")
            applied.add("deadline-unresolved")
        return min(score, 59)  # Can remain GOOD, never HOT.
    return min(score, 59)


def harden_row(row: dict[str, Any]) -> dict[str, Any] | None:
    row = dict(row)
    relevance = row.get("candidate_document_relevance")
    if not isinstance(relevance, dict) or not relevance.get("status"):
        relevance = legacy_relevance(row)
        row["candidate_document_relevance"] = relevance
    if not bool(relevance.get("proven")):
        return None

    text = f" {row.get('title') or ''} {evidence_text(row)} "
    score = int(row.get("spm_post_dce_score") or -100)
    blockers = list(row.get("spm_friction_signals") or [])
    applied: set[str] = set(blockers)
    for rx, penalty, label in FRICTION_RULES:
        if label in applied:
            continue
        if rx.search(text):
            score += penalty
            blockers.append(label)
            applied.add(label)
    score = apply_deadline_attention(row, score, blockers, applied)
    score = max(-100, min(100, score))
    row["spm_post_dce_score"] = score
    row["spm_fit_band"] = band(score)
    row["spm_friction_signals"] = blockers[:20]
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="control/gpt_review_backlog.json")
    ap.add_argument("--max-items", type=int, default=120)
    ap.add_argument("--max-portal-share", type=float, default=0.40)
    args = ap.parse_args()

    path = Path(args.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    original = [x for x in payload.get("items") or [] if isinstance(x, dict)]
    hardened = []
    dropped_unproven = 0
    for row in original:
        cooked = harden_row(row)
        if cooked is None:
            dropped_unproven += 1
        else:
            hardened.append(cooked)

    items = portfolio_select(hardened, args.max_items, args.max_portal_share)
    payload["schema"] = "GPT_REVIEW_BACKLOG_V3"
    payload["count"] = len(items)
    payload["items"] = items
    payload["portal_counts"] = dict(Counter(str(x.get("portal") or "UNKNOWN") for x in items))
    payload["fit_band_counts"] = dict(Counter(str(x.get("spm_fit_band") or "UNKNOWN") for x in items))
    payload["lane_counts"] = dict(Counter(str(x.get("review_lane") or "UNKNOWN") for x in items))
    payload["backfill_relevance_unproven_removed"] = dropped_unproven
    payload["attention_policy"] = (
        "Recall-first discovery is unchanged. This compact review index only reorders authoritative DCEs; "
        "explicit prime-ineligibility/security/onsite/non-solicitation frictions and unresolved deadline authority are down-ranked, not deleted from durable storage."
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": payload["schema"],
        "count": len(items),
        "dropped_unproven": dropped_unproven,
        "portal_counts": payload["portal_counts"],
        "fit_band_counts": payload["fit_band_counts"],
        "lane_counts": payload["lane_counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
