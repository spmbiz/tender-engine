from __future__ import annotations

import argparse
import json
from pathlib import Path

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
        elif status == "NOT_APPLICABLE" and not item.get("reason"):
            errors.append(f"{cid}: mandatory gate {gate} marked NOT_APPLICABLE without reason")

    if classification == "FINAL_SUPER_GREEN" and score and score < 90:
        errors.append(f"{cid}: FINAL_SUPER_GREEN requires coherent score >=90 when a final score is supplied")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    args = ap.parse_args()
    records = load_records(Path(args.review))
    errors = []
    for rec in records:
        if isinstance(rec, dict):
            errors.extend(validate_record(rec))
    result = {"records": len(records), "violations": len(errors), "errors": errors}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
