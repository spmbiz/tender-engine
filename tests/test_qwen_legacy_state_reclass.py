from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import merge_qwen_classification_state as merge_state

VERSION = "qwen3-4b-q4km-batch-selfheal-v1"
NOW = "2026-08-20T19:00:00+00:00"


def result_state(classification: str, *, lean: str, route: str, dce_eligible: bool):
    raw = {
        "schema": "QWEN_NOTICE_BATCH_SELFHEAL_V1",
        "canonical_notice_id": "TED:legacy",
        "input_material_fields_hash": "h1",
        "classifier_model": "Qwen3-4B",
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": merge_state.REQUIRED_PROMPT_VERSION,
        "classifier_version": VERSION,
        "business_calibration_version": merge_state.BUSINESS_CALIBRATION_VERSION,
        "classification": classification,
        "confidence": 0.0,
        "lean_attractiveness": lean,
        "delivery_mode": route,
        "friction_flags": [],
        "survival_decision": "KEEP",
        "dce_eligible": dce_eligible,
        "needs_gpt_review": False,
        "classified_at_utc": NOW,
        "parse_error": None,
    }
    state = merge_state.state_record(raw, NOW)
    # Reproduce historical state rows: merge V2 did not retain post-guard provenance.
    state["post_guard_schema"] = None
    state["post_guard_notice_context_used"] = None
    state["post_guard_context_source"] = None
    return state


def inputs():
    ledger = [{"canonical_notice_id": "TED:legacy", "material_fields_hash": "h1"}]
    queue = [{
        "canonical_notice_id": "TED:legacy",
        "material_fields_hash": "h1",
        "notice": {
            "candidate_id": "TED:legacy",
            "title": "Design and development of an accessible website",
            "description": "Public website, CMS, hosting and web maintenance services",
            "cpv_or_category": "software development",
            "procedure": "open",
        },
    }]
    return ledger, queue


def test_legacy_semantic_drift_is_removed_from_state_and_requeued():
    ledger, queue = inputs()
    previous = result_state("REJECT_OBVIOUS", lean="LOW", route="UNCLEAR", dce_eligible=False)
    state, remaining, summary = merge_state.merge(
        ledger,
        queue,
        [previous],
        [],
        target_version=VERSION,
        accepted_at=NOW,
    )
    assert state == []
    assert [x["canonical_notice_id"] for x in remaining] == ["TED:legacy"]
    assert summary["legacy_guard_drift_requeue_ids"] == ["TED:legacy"]
    assert summary["stats"]["previous_guard_semantic_drift_requeued"] == 1


def test_missing_provenance_alone_does_not_force_reclassification():
    ledger, queue = inputs()
    previous = result_state("FIT", lean="HIGH", route="DIRECT_DIGITAL", dce_eligible=True)
    state, remaining, summary = merge_state.merge(
        ledger,
        queue,
        [previous],
        [],
        target_version=VERSION,
        accepted_at=NOW,
    )
    assert len(state) == 1
    assert remaining == []
    assert summary["legacy_guard_drift_requeue_ids"] == []
    assert summary["stats"]["previous_legacy_guard_semantically_current"] == 1
