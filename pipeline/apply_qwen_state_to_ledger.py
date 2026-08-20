#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

REQUIRED_PROMPT_VERSION = "qwen-batch-high-recall-business-fit-v3-rich"
BUSINESS_CALIBRATION_VERSION = "spm-business-fit-v2"
VALID_CLASSIFICATIONS = {"STRONG_FIT", "FIT", "MAYBE", "REJECT_OBVIOUS"}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def open_text(path: Path, mode: str):
    return gzip.open(path, mode + "t", encoding="utf-8") if path.suffix == ".gz" else path.open(mode, encoding="utf-8")


def read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return []
    out: list[dict[str, Any]] = []
    with open_text(path, "r") as fh:
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
    with open_text(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def cid(row: dict[str, Any]) -> str:
    n = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    return str(
        row.get("canonical_notice_id")
        or row.get("candidate_id")
        or n.get("candidate_id")
        or n.get("i")
        or ""
    ).strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get("material_fields_hash") or row.get("input_material_fields_hash") or "").strip()


def semantic_state_reason(row: dict[str, Any], classifier_version: str) -> str | None:
    if str(row.get("classifier_version") or "") != classifier_version:
        return "wrong_classifier_version"
    if str(row.get("classifier_prompt_version") or "") != REQUIRED_PROMPT_VERSION:
        return "wrong_classifier_prompt_version"
    if str(row.get("business_calibration_version") or "") != BUSINESS_CALIBRATION_VERSION:
        return "wrong_business_calibration_version"
    if row.get("parse_error"):
        return "parse_or_fallback_error"
    if str(row.get("classification") or "").upper() not in VALID_CLASSIFICATIONS:
        return "invalid_classification"
    if not material_hash(row):
        return "missing_material_hash"
    return None


def unique_index(rows: list[dict[str, Any]], *, label: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = cid(row)
        if not candidate:
            raise SystemExit(f"{label} row missing candidate id")
        if candidate in out:
            raise SystemExit(f"duplicate candidate id in {label}: {candidate}")
        out[candidate] = row
    return out


def resolve_snapshot_path(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"snapshot path does not exist: {path}")
        return path
    for direct in (
        Path("snapshot/live-open-tenders-latest.jsonl.gz"),
        Path("snapshot/live-open-tenders-latest.jsonl"),
        Path("input/live-open-tenders-latest.jsonl.gz"),
        Path("input/live-open-tenders-latest.jsonl"),
    ):
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


def recovery_envelope(
    ledger_row: dict[str, Any],
    notice: dict[str, Any],
    *,
    reason: str,
    generated_at: str,
) -> dict[str, Any]:
    candidate = cid(ledger_row)
    return {
        "schema": "NOTICE_CHANGE_QUEUE_V1",
        "queue_reason": "STATE_INTEGRITY_RECLASSIFICATION",
        "integrity_reclassification_reasons": [reason],
        "canonical_notice_id": candidate,
        "material_fields_hash": material_hash(ledger_row),
        "previous_material_fields_hash": ledger_row.get("previous_material_fields_hash"),
        "first_seen_at": generated_at,
        "last_seen_at": ledger_row.get("last_seen_at") or generated_at,
        "notice": notice,
    }


def apply_state(
    ledger_rows: list[dict[str, Any]],
    queue_rows: list[dict[str, Any]],
    state_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    *,
    classifier_version: str,
    generated_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ledger = unique_index(ledger_rows, label="ledger")
    queue = unique_index(queue_rows, label="classification queue")
    raw_state = unique_index(state_rows, label="Qwen state") if state_rows else {}
    snapshot = unique_index(snapshot_rows, label="snapshot") if snapshot_rows else {}

    valid_state: dict[str, dict[str, Any]] = {}
    rejected = Counter()
    for candidate, row in raw_state.items():
        reason = semantic_state_reason(row, classifier_version)
        if reason:
            rejected[reason] += 1
            continue
        valid_state[candidate] = row

    applied = 0
    stale_hash = 0
    missing_exact_state = 0
    recovery_needed: dict[str, str] = {}

    for candidate, row in ledger.items():
        expected_hash = material_hash(row)
        if not expected_hash:
            raise SystemExit(f"ledger row missing material hash: {candidate}")
        s = valid_state.get(candidate)
        exact = bool(s and material_hash(s) == expected_hash)
        if exact:
            row["classifier_model"] = s.get("classifier_model")
            row["classifier_quant"] = s.get("classifier_quant")
            row["classifier_prompt_version"] = s.get("classifier_prompt_version")
            row["classifier_version"] = s.get("classifier_version")
            row["classification"] = s.get("classification")
            row["confidence"] = s.get("confidence")
            row["lean_attractiveness"] = s.get("lean_attractiveness")
            row["delivery_mode"] = s.get("delivery_mode")
            row["friction_flags"] = s.get("friction_flags") if isinstance(s.get("friction_flags"), list) else []
            row["novelty_or_unusual_flag"] = s.get("novelty_or_unusual_flag", s.get("unusual_or_novel"))
            row["needs_gpt_review"] = s.get("needs_gpt_review")
            row["survival_decision"] = s.get("survival_decision") or "KEEP"
            row["dce_eligible"] = bool(s.get("dce_eligible", True))
            row["business_calibration_version"] = s.get("business_calibration_version")
            row["classified_at"] = s.get("classified_at_utc") or s.get("classified_at")
            row["needs_reclassification"] = False
            row["classification_stale"] = False
            applied += 1
            continue

        if s is not None:
            stale_hash += 1
            recovery_needed[candidate] = "state_material_hash_mismatch"
        elif candidate in raw_state:
            reason = semantic_state_reason(raw_state[candidate], classifier_version) or "invalid_state_contract"
            recovery_needed[candidate] = reason
        elif row.get("classification"):
            # The ledger classification is a cache. If the authoritative durable
            # Qwen state no longer contains the exact row, never let that cached
            # label suppress reclassification indefinitely.
            missing_exact_state += 1
            recovery_needed[candidate] = "ledger_classification_missing_authoritative_state"
        elif bool(row.get("needs_reclassification")):
            recovery_needed[candidate] = "ledger_requires_reclassification"

        if candidate in recovery_needed:
            row["needs_reclassification"] = True
            row["classification_stale"] = bool(row.get("classification"))
            row["classification_state_integrity_reason"] = recovery_needed[candidate]

    remaining: list[dict[str, Any]] = []
    already = 0
    queue_seen: set[str] = set()
    for candidate, envelope in queue.items():
        s = valid_state.get(candidate)
        if s and material_hash(s) == material_hash(envelope):
            already += 1
            continue
        remaining.append(envelope)
        queue_seen.add(candidate)

    synthesized = 0
    synthesized_ids: list[str] = []
    for candidate in sorted(recovery_needed):
        s = valid_state.get(candidate)
        if s and material_hash(s) == material_hash(ledger[candidate]):
            continue
        if candidate in queue_seen:
            continue
        notice = snapshot.get(candidate)
        if notice is None:
            raise SystemExit(f"cannot recover classification queue without exact snapshot context: {candidate}")
        remaining.append(
            recovery_envelope(
                ledger[candidate],
                notice,
                reason=recovery_needed[candidate],
                generated_at=generated_at,
            )
        )
        queue_seen.add(candidate)
        synthesized += 1
        synthesized_ids.append(candidate)

    summary = {
        "ledger_rows": len(ledger_rows),
        "state_rows_seen": len(state_rows),
        "state_rows_semantic_contract_valid": len(valid_state),
        "state_rows_semantic_contract_rejected": dict(sorted(rejected.items())),
        "exact_hash_applied": applied,
        "stale_hash_ignored": stale_hash,
        "ledger_classifications_missing_authoritative_state": missing_exact_state,
        "queue_before": len(queue_rows),
        "queue_satisfied_from_state": already,
        "queue_recovery_candidates": len(recovery_needed),
        "queue_recovery_synthesized": synthesized,
        "queue_recovery_synthesized_ids": synthesized_ids,
        "queue_after": len(remaining),
        "snapshot_context_rows": len(snapshot),
    }
    return list(ledger.values()), remaining, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Overlay exact-contract Qwen state onto a freshly built notice ledger without changing notice identity.")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--classification-queue", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--snapshot", help="Exact immutable live snapshot; auto-discovered in the ledger job when omitted.")
    ap.add_argument("--summary", required=True)
    ap.add_argument("--classifier-version", required=True)
    args = ap.parse_args()

    ledger_path = Path(args.ledger)
    queue_path = Path(args.classification_queue)
    summary_path = Path(args.summary)
    snapshot_path = resolve_snapshot_path(args.snapshot)
    generated_at = now_utc()

    ledger_rows, remaining, audit = apply_state(
        read_jsonl(ledger_path),
        read_jsonl(queue_path),
        read_jsonl(Path(args.state)),
        read_jsonl(snapshot_path) if snapshot_path else [],
        classifier_version=args.classifier_version,
        generated_at=generated_at,
    )
    write_jsonl(ledger_path, ledger_rows)
    write_jsonl(queue_path, remaining)

    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary["target_classifier_version"] = args.classifier_version
    summary["required_classifier_prompt_version"] = REQUIRED_PROMPT_VERSION
    summary["required_business_calibration_version"] = BUSINESS_CALIBRATION_VERSION
    summary["classification_queue"] = len(remaining)
    summary["qwen_state_rows_seen"] = audit["state_rows_seen"]
    summary["qwen_state_rows_semantic_contract_valid"] = audit["state_rows_semantic_contract_valid"]
    summary["qwen_state_rows_semantic_contract_rejected"] = audit["state_rows_semantic_contract_rejected"]
    summary["qwen_state_exact_hash_applied"] = audit["exact_hash_applied"]
    summary["qwen_state_stale_hash_ignored"] = audit["stale_hash_ignored"]
    summary["ledger_classifications_missing_authoritative_state"] = audit["ledger_classifications_missing_authoritative_state"]
    summary["classification_queue_satisfied_from_state"] = audit["queue_satisfied_from_state"]
    summary["classification_queue_integrity_recovery_candidates"] = audit["queue_recovery_candidates"]
    summary["classification_queue_integrity_recovery_synthesized"] = audit["queue_recovery_synthesized"]
    summary["classification_queue_integrity_recovery_ids"] = audit["queue_recovery_synthesized_ids"]
    summary["classification_state_snapshot_source"] = str(snapshot_path) if snapshot_path else None
    summary.setdefault("rules", {})["classification_state"] = (
        "A notice is considered classified only when canonical_notice_id, material_fields_hash, classifier_version, classifier_prompt_version, business_calibration_version and a non-fallback semantic result all match the current contract. A cached ledger classification without authoritative exact state is requeued from the immutable snapshot."
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
