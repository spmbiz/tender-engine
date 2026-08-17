from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_gpt_web_review_bank import (
    compact,
    index_item,
    is_open,
    key,
    load_existing,
    load_jsonl,
    rank,
    utc_now,
)
from post_dce_scope_gate import evaluate_post_dce_scope, scope_reject_audit


def _append_audit(
    audit: list[dict[str, Any]],
    row: dict[str, Any],
    result: dict[str, Any],
    run_id: Any,
    timestamp: str,
) -> None:
    audit.append(scope_reject_audit(row, result, run_id, timestamp))


def _dedupe_audit(rows: list[dict[str, Any]], limit: int = 1000) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        cid = str(row.get("candidate_id") or "").strip().casefold()
        reasons = "|".join(str(v) for v in (row.get("scope_reject_reason_codes") or []))
        run_id = str(row.get("source_dce_run_id") or "")
        marker = (cid, reasons, run_id)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
        if len(out) >= limit:
            break
    out.reverse()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--existing")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top-out", required=True)
    ap.add_argument("--index-out", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--max-items", type=int, default=240)
    ap.add_argument("--top-items", type=int, default=30)
    args = ap.parse_args()

    now = utc_now()
    incoming_rows = [r for r in load_jsonl(Path(args.queue)) if r.get("gate_readiness")]
    existing = load_existing(Path(args.existing) if args.existing else None)

    current_rejects: list[dict[str, Any]] = []
    eligible_incoming_rows: list[dict[str, Any]] = []
    for row in incoming_rows:
        result = evaluate_post_dce_scope(row)
        if result.get("auto_reject"):
            _append_audit(current_rejects, row, result, args.run_id, now)
        else:
            eligible_incoming_rows.append(row)

    incoming = [compact(r, args.run_id) for r in eligible_incoming_rows]

    merged: dict[str, dict[str, Any]] = {}
    for row in existing.get("items") or []:
        if not isinstance(row, dict) or row.get("review_state") != "PENDING_GPT_WEB" or not is_open(row):
            continue
        result = evaluate_post_dce_scope(row)
        if result.get("auto_reject"):
            existing_run_id = row.get("source_dce_run_id") or args.run_id
            _append_audit(current_rejects, row, result, existing_run_id, now)
            continue
        merged[key(row)] = row

    # Critical migration rule: the fresh row rebuilt from the authoritative deep-review
    # queue ALWAYS replaces an older unresolved bank representation for the same ID.
    # Review ranking must never decide which schema version survives.
    for row in incoming:
        if is_open(row):
            merged[key(row)] = row

    items = sorted(merged.values(), key=rank, reverse=True)[: max(0, args.max_items)]
    source_runs: list[Any] = []
    for value in [args.run_id] + list(existing.get("source_runs") or []):
        normalized: Any = int(value) if str(value).isdigit() else value
        if normalized not in source_runs:
            source_runs.append(normalized)

    incoming_open = sum(1 for row in incoming if is_open(row))
    incoming_with_evidence = sum(1 for row in incoming if row.get("evidence_gate_coverage"))

    historical_audit = [row for row in (existing.get("scope_auto_rejects") or []) if isinstance(row, dict)]
    audit = _dedupe_audit(historical_audit + current_rejects)
    reason_counts: dict[str, int] = {}
    for row in current_rejects:
        for reason in row.get("scope_reject_reason_codes") or []:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1

    payload = {
        "schema": "GPT_WEB_DCE_REVIEW_BANK_V4",
        "updated_at": now,
        "latest_source_dce_run_id": int(args.run_id) if str(args.run_id).isdigit() else args.run_id,
        "source_runs": source_runs[:30],
        "incoming_gate_ready": len(incoming_rows),
        "incoming_scope_eligible": len(incoming),
        "incoming_scope_auto_rejected": len(incoming_rows) - len(eligible_incoming_rows),
        "scope_auto_rejected_this_rebuild": len(current_rejects),
        "scope_auto_reject_reason_counts_this_rebuild": reason_counts,
        "scope_auto_reject_audit_count": len(audit),
        "scope_auto_rejects": audit,
        "incoming_open": incoming_open,
        "incoming_with_gate_evidence": incoming_with_evidence,
        "count": len(items),
        "items": items,
        "rule": "Fresh authoritative deep-review rows replace stale representations of the same candidate ID. New generations merge without erasing unrelated unresolved open candidates. After DCE recovery, only unambiguous non-broker physical works/services are deterministically removed from GPT review; digital, mixed, ambiguous, and supply/brokerable scopes survive. SPM priority orders review only.",
        "instruction": "GPT Web adjudicates from evidence_by_gate. Never infer bidder facts. Missing evidence is UNKNOWN, never PASS. FINAL_SUPER_GREEN requires authoritative resolution of every mandatory gate and deadline.",
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    top = {
        "schema": "GPT_WEB_DCE_REVIEW_TOP_V4",
        "updated_at": now,
        "latest_source_dce_run_id": payload["latest_source_dce_run_id"],
        "pending_total": len(items),
        "incoming_gate_ready": len(incoming_rows),
        "incoming_scope_eligible": len(incoming),
        "incoming_scope_auto_rejected": payload["incoming_scope_auto_rejected"],
        "scope_auto_rejected_this_rebuild": len(current_rejects),
        "incoming_open": incoming_open,
        "incoming_with_gate_evidence": incoming_with_evidence,
        "count": min(max(0, args.top_items), len(items)),
        "items": items[: max(0, args.top_items)],
    }
    top_path = Path(args.top_out)
    top_path.parent.mkdir(parents=True, exist_ok=True)
    top_path.write_text(json.dumps(top, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    index = {
        "schema": "GPT_WEB_DCE_REVIEW_INDEX_V4",
        "updated_at": now,
        "latest_source_dce_run_id": payload["latest_source_dce_run_id"],
        "count": len(items),
        "items": [index_item(row) for row in items],
    }
    index_path = Path(args.index_out)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if incoming and not incoming_with_evidence:
        raise SystemExit("Gate-ready rows exist but zero gate evidence was packed; refusing silent empty handoff")

    print(json.dumps({
        "schema": payload["schema"],
        "incoming_gate_ready": len(incoming_rows),
        "incoming_scope_eligible": len(incoming),
        "incoming_scope_auto_rejected": payload["incoming_scope_auto_rejected"],
        "scope_auto_rejected_this_rebuild": len(current_rejects),
        "scope_auto_reject_reason_counts_this_rebuild": reason_counts,
        "incoming_open": incoming_open,
        "incoming_with_gate_evidence": incoming_with_evidence,
        "pending_total": len(items),
        "top_first": [
            {
                "candidate_id": row.get("candidate_id"),
                "spm_priority_score": row.get("spm_priority_score"),
                "title": row.get("title"),
            }
            for row in items[:5]
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
