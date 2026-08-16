from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

GATES = (
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
    "payment_tax",
)

RESOLVED_DEADLINE = {
    "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE",
    "DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
    return out


def load_existing(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def key(row: dict[str, Any]) -> str:
    cid = str(row.get("candidate_id") or "").strip().casefold()
    if cid:
        return cid
    return "|".join(str(row.get(k) or "").strip().casefold() for k in ("title", "buyer", "notice_url"))


def is_open(row: dict[str, Any]) -> bool:
    value = str(row.get("deadline") or "").strip()
    if not value:
        return True
    try:
        return date.fromisoformat(value[:10]) >= datetime.now(timezone.utc).date()
    except Exception:
        return True


def nested_candidate(row: dict[str, Any]) -> dict[str, Any]:
    candidate = row.get("candidate")
    return candidate if isinstance(candidate, dict) else {}


def first_value(row: dict[str, Any], candidate: dict[str, Any], *names: str) -> Any:
    for source in (row, candidate):
        for name in names:
            value = source.get(name)
            if value not in (None, "", [], {}):
                return value
    return None


def evidence_map(row: dict[str, Any]) -> dict[str, Any]:
    snippets = row.get("gate_snippets") or row.get("evidence_by_gate") or {}
    if not isinstance(snippets, dict):
        return {}
    # extract_gates.py has used both `categories` and `gate_evidence` containers
    # across durable handoff versions. The aggregate embeds the full gate_snippets
    # object, so unwrap either schema before reading canonical gates.
    for nested_key in ("categories", "gate_evidence", "evidence_by_gate"):
        nested = snippets.get(nested_key)
        if isinstance(nested, dict):
            return nested
    return snippets


def compact_evidence(row: dict[str, Any], per_gate: int = 4, chars: int = 1800) -> dict[str, list[dict[str, Any]]]:
    snippets = evidence_map(row)
    packed: dict[str, list[dict[str, Any]]] = {}
    for gate in GATES:
        items = snippets.get(gate) if isinstance(snippets, dict) else []
        out: list[dict[str, Any]] = []
        for item in list(items or [])[:per_gate]:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("snippet") or item.get("evidence") or "")
                source = (
                    item.get("source")
                    or item.get("file")
                    or item.get("path")
                    or item.get("document")
                    or item.get("document_path")
                )
                match = item.get("match")
                start = item.get("start")
                end = item.get("end")
            else:
                text = str(item or "")
                source = None
                match = None
                start = None
                end = None
            text = " ".join(text.split())[:chars]
            if text:
                record: dict[str, Any] = {"text": text, "source": source}
                if match not in (None, ""):
                    record["match"] = match
                if start is not None:
                    record["start"] = start
                if end is not None:
                    record["end"] = end
                out.append(record)
        packed[gate] = out
    return packed


def plain_excerpt(value: Any, max_chars: int = 1000) -> str | None:
    if value in (None, ""):
        return None
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = " ".join(text.split())
    return text[:max_chars] or None


def compact(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    candidate = nested_candidate(row)
    evidence = compact_evidence(row)
    coverage = sum(1 for items in evidence.values() if items)
    authority = row.get("authority_conflicts") or {}
    deadline = authority.get("deadline") if isinstance(authority, dict) else {}
    deadline = deadline if isinstance(deadline, dict) else {}
    deadline_status = str(deadline.get("status") or row.get("deadline_authority_status") or "MISSING")
    deadline_resolved = deadline_status in RESOLVED_DEADLINE and not bool(deadline.get("conflict") or row.get("deadline_conflict"))
    preliminary_raw = first_value(row, candidate, "preliminary_score", "priority_score", "score")
    try:
        preliminary = int(float(preliminary_raw or 0))
    except Exception:
        preliminary = 0
    return {
        "candidate_id": first_value(row, candidate, "candidate_id"),
        "title": first_value(row, candidate, "title"),
        "buyer": first_value(row, candidate, "buyer", "contracting_authority"),
        "portal": first_value(row, candidate, "portal"),
        "source": first_value(row, candidate, "source"),
        "notice_id": first_value(row, candidate, "notice_id"),
        "notice_url": first_value(row, candidate, "notice_url", "source_url", "url"),
        "deadline": first_value(row, candidate, "deadline"),
        "published": first_value(row, candidate, "published", "publication_date"),
        "estimated_value": first_value(row, candidate, "estimated_value", "value"),
        "currency": first_value(row, candidate, "currency"),
        "preliminary_score": preliminary,
        "qwen_decision": first_value(row, candidate, "qwen_decision", "decision"),
        "qwen_route": first_value(row, candidate, "qwen_route", "route"),
        "qwen_lean": first_value(row, candidate, "qwen_lean", "lean"),
        "description_excerpt": plain_excerpt(first_value(row, candidate, "description", "summary")),
        "content_quality": first_value(row, candidate, "content_quality") or row.get("content_quality"),
        "gate_readiness": bool(row.get("gate_readiness")),
        "deadline_authority": deadline,
        "deadline_authority_status": deadline_status,
        "deadline_resolved": deadline_resolved,
        "evidence_gate_coverage": coverage,
        "evidence_by_gate": evidence,
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "review_state": "PENDING_GPT_WEB",
        "review_contract": "Authoritative DCE evidence handoff only. Missing evidence is UNKNOWN, never PASS. FINAL_SUPER_GREEN requires all mandatory gates resolved and authoritative deadline reconciliation.",
    }


def rank(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(bool(row.get("deadline_resolved"))),
        int(row.get("evidence_gate_coverage") or 0),
        int(row.get("preliminary_score") or 0),
        str(row.get("candidate_id") or ""),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top-out")
    ap.add_argument("--top-items", type=int, default=30)
    ap.add_argument("--existing")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--max-items", type=int, default=240)
    args = ap.parse_args()

    incoming_rows = [r for r in load_jsonl(Path(args.queue)) if r.get("gate_readiness")]
    incoming = [compact(r, args.run_id) for r in incoming_rows]
    existing = load_existing(Path(args.existing) if args.existing else None)

    merged: dict[str, dict[str, Any]] = {}
    for row in existing.get("items") or []:
        if isinstance(row, dict) and row.get("review_state") == "PENDING_GPT_WEB" and is_open(row):
            merged[key(row)] = row
    for row in incoming:
        if not is_open(row):
            continue
        k = key(row)
        current = merged.get(k)
        if current is None or rank(row) >= rank(current):
            merged[k] = row

    items = sorted(merged.values(), key=rank, reverse=True)[: max(0, args.max_items)]
    source_runs: list[Any] = []
    for value in [args.run_id] + list(existing.get("source_runs") or []):
        normalized: Any = int(value) if str(value).isdigit() else value
        if normalized not in source_runs:
            source_runs.append(normalized)

    payload = {
        "schema": "GPT_WEB_DCE_REVIEW_BANK_V2",
        "updated_at": utc_now(),
        "latest_source_dce_run_id": int(args.run_id) if str(args.run_id).isdigit() else args.run_id,
        "source_runs": source_runs[:30],
        "incoming_gate_ready": len(incoming),
        "incoming_with_gate_evidence": sum(1 for row in incoming if row.get("evidence_gate_coverage")),
        "count": len(items),
        "items": items,
        "rule": "Persistent unresolved GPT Web review bank. New DCE generations merge; they do not erase older open unresolved candidates.",
        "instruction": "GPT Web adjudicates these rows from evidence_by_gate. Do not infer bidder facts. Unknown is never PASS. Persist resolved verdicts separately and remove them from this pending bank only after adjudication.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.top_out:
        top_path = Path(args.top_out)
        top_path.parent.mkdir(parents=True, exist_ok=True)
        top_payload = {
            "schema": "GPT_WEB_DCE_REVIEW_TOP_V1",
            "updated_at": payload["updated_at"],
            "latest_source_dce_run_id": payload["latest_source_dce_run_id"],
            "pending_total": payload["count"],
            "incoming_gate_ready": payload["incoming_gate_ready"],
            "incoming_with_gate_evidence": payload["incoming_with_gate_evidence"],
            "count": min(max(0, args.top_items), len(items)),
            "items": items[: max(0, args.top_items)],
        }
        top_path.write_text(json.dumps(top_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "incoming_gate_ready": len(incoming),
        "incoming_with_gate_evidence": payload["incoming_with_gate_evidence"],
        "pending_total": len(items),
        "out": str(out),
        "top_out": args.top_out,
    }, indent=2))


if __name__ == "__main__":
    main()
