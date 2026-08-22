#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from qwen_notice_post_guard import guard as current_post_guard
except ImportError:  # importlib/package execution in tests
    from pipeline.qwen_notice_post_guard import guard as current_post_guard

STATE_SCHEMA = "NOTICE_CLASSIFICATION_STATE_V1"
SUMMARY_SCHEMA = "NOTICE_CLASSIFICATION_STATE_MERGE_SUMMARY_V5_REQUEUE_SAFE"
BUSINESS_CALIBRATION_VERSION = "spm-business-fit-v2"
REQUIRED_PROMPT_VERSION = "qwen-batch-high-recall-business-fit-v3-rich"
EXACT_POST_GUARD_PREFIX = "QWEN_NOTICE_POST_GUARD_V5_"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def opener(path: Path, mode: str):
    return gzip.open(path, mode + "t", encoding="utf-8") if path.suffix == ".gz" else path.open(mode, encoding="utf-8")


def read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return []
    out: list[dict[str, Any]] = []
    with opener(path, "r") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception as exc:
                raise SystemExit(f"invalid JSONL row {path}:{lineno}: {type(exc).__name__}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"non-object JSONL row {path}:{lineno}")
            out.append(row)
    return out


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with opener(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def cid(row: dict[str, Any]) -> str:
    n = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    return str(
        row.get("canonical_notice_id")
        or row.get("candidate_id")
        or row.get("id")
        or n.get("candidate_id")
        or n.get("i")
        or ""
    ).strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get("input_material_fields_hash") or row.get("material_fields_hash") or "").strip()


def semantic_contract_matches(row: dict[str, Any], target_version: str) -> bool:
    if target_version and str(row.get("classifier_version") or "").strip() != target_version:
        return False
    if str(row.get("classifier_prompt_version") or "").strip() != REQUIRED_PROMPT_VERSION:
        return False
    if str(row.get("business_calibration_version") or "") != BUSINESS_CALIBRATION_VERSION:
        return False
    if row.get("parse_error"):
        return False
    return True


def is_valid_result(row: dict[str, Any], expected_hash: str, target_version: str) -> tuple[bool, str]:
    if not cid(row):
        return False, "missing_id"
    h = material_hash(row)
    if not h:
        return False, "missing_input_hash"
    if h != expected_hash:
        return False, "stale_material_hash"
    if row.get("parse_error"):
        return False, "parse_or_fallback_error"
    version = str(row.get("classifier_version") or "").strip()
    if not version:
        return False, "missing_classifier_version"
    if target_version and version != target_version:
        return False, "wrong_classifier_version"
    if str(row.get("classifier_prompt_version") or "").strip() != REQUIRED_PROMPT_VERSION:
        return False, "wrong_classifier_prompt_version"
    if str(row.get("business_calibration_version") or "") != BUSINESS_CALIBRATION_VERSION:
        return False, "wrong_business_calibration_version"
    classification = str(row.get("classification") or row.get("decision") or "").upper()
    if classification not in {"STRONG_FIT", "FIT", "MAYBE", "REJECT_OBVIOUS"}:
        return False, "invalid_classification"
    return True, "accepted"


def semantic_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    flags = tuple(sorted(str(x).upper() for x in (row.get("friction_flags") or []) if x is not None))
    return (
        str(row.get("classification") or row.get("decision") or "").upper(),
        str(row.get("lean_attractiveness") or "").upper(),
        str(row.get("delivery_mode") or row.get("possible_delivery_route") or "").upper(),
        flags,
        bool(row.get("novelty_or_unusual_flag", row.get("unusual_or_novel", False))),
        bool(row.get("needs_gpt_review")),
        str(row.get("survival_decision") or "KEEP").upper(),
        bool(row.get("dce_eligible", True)),
    )


def deterministic_result_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("classified_at_utc") or row.get("classified_at") or ""),
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def has_exact_post_guard_provenance(row: dict[str, Any]) -> bool:
    return bool(row.get("post_guard_notice_context_used")) and str(row.get("post_guard_schema") or "").startswith(EXACT_POST_GUARD_PREFIX)


def legacy_guard_audit(
    row: dict[str, Any], exact_context: dict[str, Any]
) -> tuple[dict[str, Any], bool, list[str]]:
    """Audit a legacy row and return a provenance-complete replacement.

    Semantically unchanged rows are persisted with exact-context post-guard
    provenance, making the expensive full-snapshot audit a one-time migration.
    """
    audited = current_post_guard(row, exact_context, context_source="merge_legacy_state_audit")
    drifted = semantic_signature(audited) != semantic_signature(row)
    return audited, drifted, list(audited.get("post_guard_actions") or [])


def state_record(row: dict[str, Any], accepted_at: str) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "canonical_notice_id": cid(row),
        "material_fields_hash": material_hash(row),
        "classifier_model": row.get("classifier_model"),
        "classifier_quant": row.get("classifier_quant"),
        "classifier_prompt_version": row.get("classifier_prompt_version"),
        "classifier_version": row.get("classifier_version"),
        "classification": str(row.get("classification") or row.get("decision") or "").upper(),
        "confidence": row.get("confidence"),
        "lean_attractiveness": row.get("lean_attractiveness"),
        "delivery_mode": row.get("delivery_mode") or row.get("possible_delivery_route"),
        "friction_flags": row.get("friction_flags") if isinstance(row.get("friction_flags"), list) else [],
        "novelty_or_unusual_flag": row.get("novelty_or_unusual_flag", row.get("unusual_or_novel")),
        "needs_gpt_review": row.get("needs_gpt_review"),
        "survival_decision": row.get("survival_decision") or "KEEP",
        "dce_eligible": bool(row.get("dce_eligible", True)),
        "business_calibration_version": row.get("business_calibration_version"),
        "classified_at_utc": row.get("classified_at_utc") or row.get("classified_at") or accepted_at,
        "source_ledger_generation": row.get("source_ledger_generation"),
        "source_result_schema": row.get("schema"),
        "classifier_run_id": row.get("classifier_run_id") or row.get("run_id"),
        "classifier_worker_id": row.get("classifier_worker_id") or row.get("worker"),
        "initial_batch_size": row.get("initial_batch_size"),
        "effective_batch_size": row.get("effective_batch_size"),
        "self_heal_depth": row.get("self_heal_depth"),
        "recovered_after_split": row.get("recovered_after_split"),
        "deterministic_guard_actions": row.get("deterministic_guard_actions") if isinstance(row.get("deterministic_guard_actions"), list) else [],
        "post_guard_schema": row.get("post_guard_schema"),
        "post_guard_actions": row.get("post_guard_actions") if isinstance(row.get("post_guard_actions"), list) else [],
        "post_guard_applied": bool(row.get("post_guard_applied", False)),
        "post_guard_notice_context_used": row.get("post_guard_notice_context_used"),
        "post_guard_context_source": row.get("post_guard_context_source"),
        "pre_post_guard_classification": row.get("pre_post_guard_classification"),
        "pre_post_guard_delivery_mode": row.get("pre_post_guard_delivery_mode"),
        "accepted_into_state_at": accepted_at,
    }


def _unique_index(rows: list[dict[str, Any]], *, label: str, require_hash: bool = False) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = cid(row)
        if not candidate:
            raise ValueError(f"{label} row missing canonical candidate id")
        if candidate in out:
            raise ValueError(f"duplicate candidate id in {label}: {candidate}")
        if require_hash and not material_hash(row):
            raise ValueError(f"{label} row missing material hash: {candidate}")
        out[candidate] = row
    return out


def _snapshot_index(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not rows:
        return {}
    return _unique_index(rows, label="snapshot", require_hash=False)


def _integrity_envelope(
    candidate: str,
    notice: dict[str, Any],
    ledger_row: dict[str, Any],
    expected_hash: str,
    accepted_at: str,
    reasons: set[str],
) -> dict[str, Any]:
    return {
        "schema": "NOTICE_CHANGE_QUEUE_V1",
        "queue_reason": "INTEGRITY_RECLASSIFICATION",
        "integrity_reclassification_reasons": sorted(reasons),
        "canonical_notice_id": candidate,
        "material_fields_hash": expected_hash,
        "previous_material_fields_hash": ledger_row.get("previous_material_fields_hash"),
        # Make integrity repairs recent carryover without pretending the notice was
        # materially UPDATED. NEW/UPDATED still retain the highest freshness rank.
        "first_seen_at": accepted_at,
        "last_seen_at": ledger_row.get("last_seen_at") or accepted_at,
        "notice": notice,
    }


def merge(
    ledger_rows: list[dict[str, Any]],
    queue_rows: list[dict[str, Any]],
    previous_state_rows: list[dict[str, Any]],
    result_groups: list[list[dict[str, Any]]],
    *,
    target_version: str,
    accepted_at: str,
    snapshot_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ledger = _unique_index(ledger_rows, label="ledger", require_hash=True)
    current_hash = {candidate: material_hash(row) for candidate, row in ledger.items()}
    queue_index = _unique_index(queue_rows, label="classification queue", require_hash=True)
    snapshot = _snapshot_index(snapshot_rows)

    # Residual queue rows always contain exact context for themselves. The full
    # immutable snapshot is required to audit already-classified legacy state,
    # because apply_qwen_state_to_ledger intentionally removes those rows from the
    # published residual classification queue.
    queue_context = {
        candidate: (row.get("notice") if isinstance(row.get("notice"), dict) else row)
        for candidate, row in queue_index.items()
    }

    state: dict[str, dict[str, Any]] = {}
    stats = Counter()
    force_requeue: dict[str, set[str]] = defaultdict(set)
    legacy_guard_drift_ids: list[str] = []
    legacy_guard_drift_actions = Counter()
    previous_seen: set[str] = set()

    for row in previous_state_rows:
        candidate = cid(row)
        if not candidate:
            raise ValueError("previous state row missing candidate id")
        if candidate in previous_seen:
            raise ValueError(f"duplicate candidate id in previous state: {candidate}")
        previous_seen.add(candidate)
        if candidate not in current_hash:
            stats["previous_orphan_dropped"] += 1
            continue
        if material_hash(row) != current_hash[candidate]:
            stats["previous_stale_dropped"] += 1
            force_requeue[candidate].add("stale_material_hash")
            continue
        if target_version and str(row.get("classifier_version") or "") != target_version:
            stats["previous_wrong_version_dropped"] += 1
            force_requeue[candidate].add("wrong_classifier_version")
            continue
        if str(row.get("classifier_prompt_version") or "") != REQUIRED_PROMPT_VERSION:
            stats["previous_wrong_prompt_dropped"] += 1
            force_requeue[candidate].add("wrong_classifier_prompt_version")
            continue
        if str(row.get("business_calibration_version") or "") != BUSINESS_CALIBRATION_VERSION:
            stats["previous_wrong_business_calibration_dropped"] += 1
            force_requeue[candidate].add("wrong_business_calibration_version")
            continue

        if not has_exact_post_guard_provenance(row):
            stats["previous_missing_exact_post_guard_provenance"] += 1
            exact_context = snapshot.get(candidate) or queue_context.get(candidate)
            if exact_context is None:
                stats["previous_legacy_guard_audit_context_missing"] += 1
            else:
                audited, drifted, actions = legacy_guard_audit(row, exact_context)
                stats["previous_legacy_guard_audited"] += 1
                if drifted:
                    legacy_guard_drift_ids.append(candidate)
                    force_requeue[candidate].add("legacy_exact_context_guard_drift")
                    stats["previous_guard_semantic_drift_requeued"] += 1
                    legacy_guard_drift_actions.update(actions or ["semantic_signature_changed"])
                    continue
                stats["previous_legacy_guard_semantically_current"] += 1
                audited["legacy_post_guard_provenance_migrated_at"] = accepted_at
                row = audited
                stats["previous_legacy_guard_provenance_migrated"] += 1

        state[candidate] = row
        stats["previous_carried"] += 1

    reject_reasons = Counter()
    valid_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in result_groups:
        for row in group:
            candidate = cid(row)
            if not candidate or candidate not in current_hash:
                reject_reasons["unknown_or_missing_id"] += 1
                continue
            ok, reason = is_valid_result(row, current_hash[candidate], target_version)
            if not ok:
                reject_reasons[reason] += 1
                continue
            valid_by_candidate[candidate].append(row)
            stats["valid_result_rows"] += 1

    conflicting_ids: list[str] = []
    for candidate in sorted(valid_by_candidate):
        rows = valid_by_candidate[candidate]
        if len(rows) > 1:
            stats["duplicate_valid_result_rows"] += len(rows) - 1
        signatures = {semantic_signature(row) for row in rows}
        if len(signatures) > 1:
            state.pop(candidate, None)
            conflicting_ids.append(candidate)
            force_requeue[candidate].add("conflicting_valid_results")
            stats["conflicting_candidates_requeued"] += 1
            stats["conflicting_result_rows"] += len(rows)
            reject_reasons["conflicting_valid_results"] += len(rows)
            continue
        if len(rows) > 1:
            stats["duplicate_equivalent_candidates_collapsed"] += 1
        chosen = max(rows, key=deterministic_result_key)
        state[candidate] = state_record(chosen, accepted_at)
        stats["results_accepted"] += 1

    synthetic: list[dict[str, Any]] = []
    synthetic_ids: list[str] = []
    for candidate in sorted(force_requeue):
        state_row = state.get(candidate)
        if state_row and material_hash(state_row) == current_hash.get(candidate) and semantic_contract_matches(state_row, target_version):
            continue
        if candidate in queue_index:
            continue
        exact_notice = snapshot.get(candidate)
        if exact_notice is None:
            # A reclassification request without its exact canonical notice would
            # otherwise silently disappear after state invalidation. Fail closed.
            raise ValueError(f"cannot synthesize integrity reclassification without exact snapshot context: {candidate}")
        synthetic.append(
            _integrity_envelope(
                candidate,
                exact_notice,
                ledger[candidate],
                current_hash[candidate],
                accepted_at,
                force_requeue[candidate],
            )
        )
        synthetic_ids.append(candidate)
        stats["integrity_requeue_synthesized"] += 1

    filtered_queue: list[dict[str, Any]] = []
    queue_seen: set[str] = set()
    # Synthetic repairs are emitted before the residual queue. The shard builder
    # still gives truly NEW/UPDATED notices rank 0; integrity repairs use a fresh
    # first_seen timestamp and therefore stay ahead of historical backfill.
    for envelope in synthetic + queue_rows:
        candidate = cid(envelope)
        if not candidate:
            raise ValueError("classification queue row missing candidate id during output")
        if candidate in queue_seen:
            continue
        queue_seen.add(candidate)
        h = material_hash(envelope)
        if not h or h != current_hash.get(candidate):
            raise ValueError(f"classification queue material hash mismatch: {candidate}")
        state_row = state.get(candidate)
        if state_row and material_hash(state_row) == h and semantic_contract_matches(state_row, target_version):
            stats["queue_already_classified"] += 1
            continue
        filtered_queue.append(envelope)
        stats["queue_remaining"] += 1

    pending_force_ids = sorted(candidate for candidate in force_requeue if candidate not in state)
    state_rows = [state[k] for k in sorted(state)]
    summary = {
        "schema": SUMMARY_SCHEMA,
        "generated_at": accepted_at,
        "target_classifier_version": target_version,
        "required_classifier_prompt_version": REQUIRED_PROMPT_VERSION,
        "required_business_calibration_version": BUSINESS_CALIBRATION_VERSION,
        "ledger_notices": len(current_hash),
        "snapshot_context_rows": len(snapshot),
        "previous_state_rows": len(previous_state_rows),
        "result_rows_seen": sum(len(x) for x in result_groups),
        "state_rows_after_merge": len(state_rows),
        "input_queue_rows": len(queue_rows),
        "remaining_classification_queue": len(filtered_queue),
        "classified_fraction_of_ledger": round(len(state_rows) / len(current_hash), 8) if current_hash else 0.0,
        "legacy_guard_drift_requeue_ids": sorted(legacy_guard_drift_ids),
        "legacy_guard_drift_actions": dict(sorted(legacy_guard_drift_actions.items())),
        "conflicting_candidate_ids": conflicting_ids,
        "forced_reclassification_ids": pending_force_ids,
        "forced_reclassification_reasons": {k: sorted(v) for k, v in sorted(force_requeue.items()) if k in pending_force_ids},
        "synthetic_integrity_requeue_ids": synthetic_ids,
        "stats": dict(sorted(stats.items())),
        "rejected_result_reasons": dict(sorted(reject_reasons.items())),
        "safety": {
            "exact_material_hash_required": True,
            "exact_prompt_version_required": True,
            "exact_business_calibration_required": True,
            "parse_or_fallback_result_marks_classified": False,
            "wrong_classifier_version_marks_classified": False,
            "stale_result_can_overwrite_updated_notice": False,
            "legacy_state_semantic_drift_is_requeued": True,
            "legacy_semantically_current_state_is_provenance_migrated": True,
            "invalidated_state_without_residual_queue_is_synthesized_from_snapshot": True,
            "missing_snapshot_for_required_synthetic_requeue_fails_closed": True,
            "conflicting_valid_results_are_requeued": True,
            "artifact_order_resolves_semantic_conflict": False,
            "new_state_preserves_guard_and_selfheal_provenance": True,
            "malformed_jsonl_is_silently_skipped": False,
            "classification_is_not_dce_or_eligibility_truth": True,
        },
    }
    return state_rows, filtered_queue, summary


def resolve_effective_queue_path(path: Path) -> tuple[Path, str]:
    """Use the plan-stage work queue in aggregate/conveyor when it is present.

    The live input artifact contains both the original ledger residual queue and
    the plan's hash/prompt/guard-safe qwen-work-queue. Reverting to the original
    queue during aggregation used to lose integrity requeues discovered at plan.
    """
    planned = path.parent / "qwen-work-queue.jsonl.gz"
    if planned.exists() and planned != path:
        return planned, "plan_prefilter_qwen_work_queue"
    planned_plain = path.parent / "qwen-work-queue.jsonl"
    if planned_plain.exists() and planned_plain != path:
        return planned_plain, "plan_prefilter_qwen_work_queue"
    return path, "requested_classification_queue"


def resolve_snapshot_path(explicit: str | None, queue_path: Path) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"snapshot path does not exist: {path}")
        return path
    for name in ("live-open-tenders-latest.jsonl.gz", "live-open-tenders-latest.jsonl"):
        direct = queue_path.parent / name
        if direct.exists():
            return direct
    candidates = sorted(
        p for p in Path(".").rglob("live-open-tenders-latest.jsonl*")
        if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.gz"))
    )
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise SystemExit("multiple live snapshot candidates found; pass --snapshot explicitly")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge Qwen semantic results into durable hash-safe classification state.")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--classification-queue", required=True)
    ap.add_argument("--snapshot", help="Exact immutable live snapshot; auto-discovered beside the queue when omitted.")
    ap.add_argument("--previous-state")
    ap.add_argument("--results", action="append", default=[])
    ap.add_argument("--target-classifier-version", required=True)
    ap.add_argument("--state-out", required=True)
    ap.add_argument("--queue-out", required=True)
    ap.add_argument("--summary-out", required=True)
    args = ap.parse_args()

    accepted_at = now_utc()
    requested_queue = Path(args.classification_queue)
    effective_queue, queue_source = resolve_effective_queue_path(requested_queue)
    snapshot_path = resolve_snapshot_path(args.snapshot, effective_queue)
    state, queue, summary = merge(
        read_jsonl(Path(args.ledger)),
        read_jsonl(effective_queue),
        read_jsonl(Path(args.previous_state)) if args.previous_state else [],
        [read_jsonl(Path(p)) for p in args.results],
        target_version=args.target_classifier_version,
        accepted_at=accepted_at,
        snapshot_rows=read_jsonl(snapshot_path) if snapshot_path else [],
    )
    summary["requested_classification_queue"] = str(requested_queue)
    summary["effective_classification_queue"] = str(effective_queue)
    summary["classification_queue_source"] = queue_source
    summary["snapshot_source"] = str(snapshot_path) if snapshot_path else None
    write_jsonl(Path(args.state_out), state)
    write_jsonl(Path(args.queue_out), queue)
    Path(args.summary_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
