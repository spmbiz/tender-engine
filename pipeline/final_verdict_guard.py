from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from post_dce_scope_gate import evaluate_post_dce_scope

REQUIRED_GATES = [
    "entity_geography",
    "turnover_financial",
    "references_experience",
    "certifications_partner",
    "staffing_team",
    "insurance_bonds",
    "subcontracting_consortium",
    "deliverables_scope",
    "sla_onsite",
    "term_value",
    "award_criteria",
    "forms_signatures",
    "submission",
    "ip_data_security",
]
ALLOWED_RESOLVED = {"PASS", "PASS_CONDITIONAL", "NOT_APPLICABLE"}
FINAL_GREEN = {"FINAL_SUPER_GREEN"}
MODEL_REVIEW = "MODEL_REVIEW_REQUIRED"


def load_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(x) for x in text.splitlines() if x.strip()]
    obj = json.loads(text)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and isinstance(obj.get("candidates"), list):
        return obj["candidates"]
    return [obj] if isinstance(obj, dict) else []


def write_records(path: Path, records: list[dict]) -> None:
    if path.suffix.lower() == ".jsonl":
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records)
    else:
        text = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _classification(rec: dict) -> str:
    return str(rec.get("final_classification") or rec.get("classification") or rec.get("verdict") or "").upper()


def _score(rec: dict) -> int:
    for k in ("final_score", "score"):
        try:
            if rec.get(k) is not None:
                return int(float(rec[k]))
        except Exception:
            pass
    return 0


def _gate_ready(rec: dict) -> bool:
    eq = rec.get("evidence_quality") or {}
    if not isinstance(eq, dict):
        eq = {}
    return bool(eq.get("gate_readiness", rec.get("gate_readiness", False)))


def apply_post_dce_scope_guard(rec: dict) -> bool:
    """Resolve only authoritative, obvious physical non-broker scopes before GPT Web.

    Qwen stays recall-first. Ambiguous, digital, mixed and supply/brokerable rows remain
    MODEL_REVIEW_REQUIRED. This guard runs only after DCE evidence is gate-ready.
    """
    if _classification(rec) != MODEL_REVIEW or not _gate_ready(rec):
        return False
    result = evaluate_post_dce_scope(rec)
    if not result.get("auto_reject"):
        return False

    previous = _classification(rec)
    rec["classification"] = "RED"
    if "final_classification" in rec:
        rec["final_classification"] = "RED"
    if rec.get("final_score") is not None:
        rec["final_score"] = min(_score(rec), 0)
    rec["scope_auto_rejected"] = True
    rec["deterministic_scope_reject"] = {
        "previous_classification": previous,
        "classification": "RED",
        "reason_codes": list(result.get("reason_codes") or []),
        "matched_patterns": list(result.get("matched_patterns") or []),
        "digital_override": bool(result.get("digital_override")),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "contract": "Post-DCE deterministic scope reject only; digital, mixed, ambiguous and supply/brokerable scopes are not hard rejected here.",
    }
    return True


def validate_record(rec: dict) -> list[str]:
    errors: list[str] = []
    cid = str(rec.get("candidate_id") or "<missing-id>")
    classification = _classification(rec)
    score = _score(rec)
    final_attempt = classification in FINAL_GREEN or score >= 90
    if not final_attempt:
        return errors

    eq = rec.get("evidence_quality") or {}
    quality = str(eq.get("content_quality") or rec.get("content_quality") or "")
    gate_ready = bool(eq.get("gate_readiness", rec.get("gate_readiness", False)))
    if not gate_ready or quality not in {"SUBSTANTIVE_DCE_PRESENT", "MIXED_SUBSTANTIVE_AND_GUIDE"}:
        errors.append(f"{cid}: final/90+ forbidden: authoritative DCE gate_readiness not proven (quality={quality!r})")

    authority = rec.get("authority_conflicts") or {}
    deadline_authority = authority.get("deadline") if isinstance(authority, dict) else None
    if not isinstance(deadline_authority, dict):
        errors.append(f"{cid}: final/90+ forbidden: authoritative deadline reconciliation missing")
    else:
        deadline_status = str(deadline_authority.get("status") or "UNKNOWN")
        if deadline_authority.get("conflict") or deadline_status == "DEADLINE_CONFLICT_REVIEW_REQUIRED":
            errors.append(f"{cid}: final/90+ forbidden: deadline conflict requires explicit reconciliation")
        elif deadline_status in {"UNKNOWN_NO_DCE_DEADLINE_PARSED", "UNKNOWN"}:
            errors.append(f"{cid}: final/90+ forbidden: DCE submission deadline not authoritatively resolved")

    gates = rec.get("gates") or rec.get("gate_verdicts") or {}
    for gate in REQUIRED_GATES:
        item = gates.get(gate)
        if not isinstance(item, dict):
            errors.append(f"{cid}: missing mandatory gate {gate}")
            continue
        status = str(item.get("status") or "UNKNOWN").upper()
        if status not in ALLOWED_RESOLVED:
            errors.append(f"{cid}: mandatory gate {gate} unresolved/failed ({status})")
            continue
        if status in {"PASS", "PASS_CONDITIONAL"}:
            evidence = item.get("evidence") or item.get("source_refs") or item.get("snippets")
            if not evidence:
                errors.append(f"{cid}: mandatory gate {gate} has {status} without evidence")
        elif status == "NOT_APPLICABLE":
            reason = item.get("reason") or item.get("notes")
            if not reason:
                errors.append(f"{cid}: mandatory gate {gate} marked NOT_APPLICABLE without reason")

    if classification == "FINAL_SUPER_GREEN" and score and score < 90:
        errors.append(f"{cid}: FINAL_SUPER_GREEN requires coherent score >=90 when a final score is supplied")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    args = ap.parse_args()
    path = Path(args.review)
    records = load_records(path)
    errors: list[str] = []
    scope_rejected = 0

    for rec in records:
        if isinstance(rec, dict):
            scope_rejected += int(apply_post_dce_scope_guard(rec))
            errors.extend(validate_record(rec))

    result = {
        "records": len(records),
        "scope_auto_rejected": scope_rejected,
        "violations": len(errors),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    if scope_rejected:
        write_records(path, records)


if __name__ == "__main__":
    main()
