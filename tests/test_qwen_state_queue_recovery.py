from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import apply_qwen_state_to_ledger as apply_state
import merge_qwen_classification_state as merge_state

VERSION = "qwen3-4b-q4km-batch-selfheal-v1"
NOW = "2026-08-20T20:00:00+00:00"
CID = "TED:recover-me"
HASH = "hash-current"


def snapshot_notice():
    return {
        "candidate_id": CID,
        "source": "TED",
        "title": "Development of public website and CMS",
        "description": "Website design, implementation, hosting and maintenance",
        "cpv_or_category": "software development",
        "procedure": "open",
    }


def ledger_row(**kw):
    row = {
        "canonical_notice_id": CID,
        "material_fields_hash": HASH,
        "previous_material_fields_hash": None,
        "first_seen_at": "2026-08-01T00:00:00+00:00",
        "last_seen_at": NOW,
        "classification": None,
        "classifier_version": None,
        "classifier_prompt_version": None,
        "needs_reclassification": True,
    }
    row.update(kw)
    return row


def state_row(**kw):
    row = {
        "schema": merge_state.STATE_SCHEMA,
        "canonical_notice_id": CID,
        "material_fields_hash": HASH,
        "classifier_model": "Qwen3-4B",
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": merge_state.REQUIRED_PROMPT_VERSION,
        "classifier_version": VERSION,
        "classification": "FIT",
        "confidence": 0.8,
        "lean_attractiveness": "HIGH",
        "delivery_mode": "DIRECT_DIGITAL",
        "friction_flags": [],
        "needs_gpt_review": False,
        "survival_decision": "KEEP",
        "dce_eligible": True,
        "business_calibration_version": merge_state.BUSINESS_CALIBRATION_VERSION,
        "classified_at_utc": NOW,
        "parse_error": None,
    }
    row.update(kw)
    return row


def queue_envelope():
    return {
        "canonical_notice_id": CID,
        "material_fields_hash": HASH,
        "queue_reason": "CLASSIFIER_VERSION_OR_UNCLASSIFIED",
        "notice": snapshot_notice(),
    }


def test_merge_synthesizes_reclass_when_legacy_state_was_removed_from_residual_queue():
    legacy = state_row(
        classification="REJECT_OBVIOUS",
        lean_attractiveness="LOW",
        delivery_mode="UNCLEAR",
        dce_eligible=False,
        post_guard_schema=None,
        post_guard_notice_context_used=None,
    )
    state, remaining, summary = merge_state.merge(
        [ledger_row()],
        [],
        [legacy],
        [],
        target_version=VERSION,
        accepted_at=NOW,
        snapshot_rows=[snapshot_notice()],
    )
    assert state == []
    assert len(remaining) == 1
    assert remaining[0]["canonical_notice_id"] == CID
    assert remaining[0]["queue_reason"] == "INTEGRITY_RECLASSIFICATION"
    assert "legacy_exact_context_guard_drift" in remaining[0]["integrity_reclassification_reasons"]
    assert summary["synthetic_integrity_requeue_ids"] == [CID]
    assert summary["stats"]["integrity_requeue_synthesized"] == 1


def test_merge_wrong_prompt_cannot_disappear_when_residual_queue_was_already_filtered():
    previous = state_row(classifier_prompt_version="obsolete-prompt")
    state, remaining, summary = merge_state.merge(
        [ledger_row()],
        [],
        [previous],
        [],
        target_version=VERSION,
        accepted_at=NOW,
        snapshot_rows=[snapshot_notice()],
    )
    assert state == []
    assert [x["canonical_notice_id"] for x in remaining] == [CID]
    assert summary["forced_reclassification_reasons"][CID] == ["wrong_classifier_prompt_version"]


def test_merge_uses_plan_work_queue_during_aggregate(tmp_path: Path):
    original = tmp_path / "notice-classification-queue-latest.jsonl.gz"
    planned = tmp_path / "qwen-work-queue.jsonl.gz"
    original.write_bytes(b"x")
    planned.write_bytes(b"y")
    chosen, source = merge_state.resolve_effective_queue_path(original)
    assert chosen == planned
    assert source == "plan_prefilter_qwen_work_queue"


def test_apply_state_recovers_cached_ledger_classification_missing_from_authoritative_state():
    ledger = ledger_row(
        classification="FIT",
        classifier_version=VERSION,
        classifier_prompt_version=merge_state.REQUIRED_PROMPT_VERSION,
        needs_reclassification=False,
    )
    out_ledger, remaining, audit = apply_state.apply_state(
        [ledger],
        [],
        [],
        [snapshot_notice()],
        classifier_version=VERSION,
        generated_at=NOW,
    )
    assert len(out_ledger) == 1
    assert out_ledger[0]["needs_reclassification"] is True
    assert out_ledger[0]["classification_stale"] is True
    assert len(remaining) == 1
    assert remaining[0]["queue_reason"] == "STATE_INTEGRITY_RECLASSIFICATION"
    assert audit["ledger_classifications_missing_authoritative_state"] == 1
    assert audit["queue_recovery_synthesized"] == 1


def test_apply_state_rejects_wrong_prompt_and_synthesizes_queue():
    invalid = state_row(classifier_prompt_version="old-thin-prompt")
    out_ledger, remaining, audit = apply_state.apply_state(
        [ledger_row(classification="FIT", needs_reclassification=False)],
        [],
        [invalid],
        [snapshot_notice()],
        classifier_version=VERSION,
        generated_at=NOW,
    )
    assert out_ledger[0]["needs_reclassification"] is True
    assert len(remaining) == 1
    assert audit["state_rows_semantic_contract_rejected"]["wrong_classifier_prompt_version"] == 1


def test_apply_state_valid_exact_contract_satisfies_existing_queue():
    out_ledger, remaining, audit = apply_state.apply_state(
        [ledger_row()],
        [queue_envelope()],
        [state_row()],
        [snapshot_notice()],
        classifier_version=VERSION,
        generated_at=NOW,
    )
    assert remaining == []
    assert out_ledger[0]["classification"] == "FIT"
    assert out_ledger[0]["needs_reclassification"] is False
    assert audit["exact_hash_applied"] == 1
    assert audit["queue_satisfied_from_state"] == 1


def test_semantically_current_legacy_guard_provenance_is_migrated_once():
    legacy = state_row(
        post_guard_schema=None,
        post_guard_notice_context_used=None,
        post_guard_context_source=None,
    )
    first_state, first_remaining, first_summary = merge_state.merge(
        [ledger_row()],
        [],
        [legacy],
        [],
        target_version=VERSION,
        accepted_at=NOW,
        snapshot_rows=[snapshot_notice()],
    )
    assert first_remaining == []
    assert len(first_state) == 1
    migrated = first_state[0]
    assert migrated["post_guard_schema"].startswith(merge_state.EXACT_POST_GUARD_PREFIX)
    assert migrated["post_guard_notice_context_used"] is True
    assert migrated["post_guard_context_source"] == "merge_legacy_state_audit"
    assert migrated["legacy_post_guard_provenance_migrated_at"] == NOW
    assert first_summary["stats"]["previous_legacy_guard_provenance_migrated"] == 1

    second_state, second_remaining, second_summary = merge_state.merge(
        [ledger_row()],
        [],
        first_state,
        [],
        target_version=VERSION,
        accepted_at=NOW,
        snapshot_rows=[snapshot_notice()],
    )
    assert second_remaining == []
    assert len(second_state) == 1
    assert second_summary["stats"].get("previous_legacy_guard_audited", 0) == 0
    assert second_summary["stats"].get("previous_legacy_guard_provenance_migrated", 0) == 0
