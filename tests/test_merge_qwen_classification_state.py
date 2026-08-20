from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "pipeline" / "merge_qwen_classification_state.py"
spec = importlib.util.spec_from_file_location("merge_state", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

VERSION = "qwen-prod-v1"
NOW = "2026-08-16T02:20:00+00:00"
BUSINESS_CALIBRATION_VERSION = mod.BUSINESS_CALIBRATION_VERSION


def ledger(cid="TED:1", h="h1"):
    return {"canonical_notice_id": cid, "material_fields_hash": h}


def queue(cid="TED:1", h="h1"):
    return {"canonical_notice_id": cid, "material_fields_hash": h, "notice": {"candidate_id": cid, "title": "Website"}}


def result(cid="TED:1", h="h1", **kw):
    row = {
        "schema": "QWEN_NOTICE_BATCH_SELFHEAL_V1",
        "canonical_notice_id": cid,
        "input_material_fields_hash": h,
        "classifier_model": "Qwen3-4B",
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": mod.REQUIRED_PROMPT_VERSION,
        "classifier_version": VERSION,
        "business_calibration_version": BUSINESS_CALIBRATION_VERSION,
        "classification": "FIT",
        "confidence": 0.9,
        "lean_attractiveness": "HIGH",
        "delivery_mode": "DIRECT_DIGITAL",
        "friction_flags": [],
        "classified_at_utc": NOW,
        "parse_error": None,
        "post_guard_schema": "QWEN_NOTICE_POST_GUARD_V5_EXACT_CONTEXT",
        "post_guard_actions": [],
        "post_guard_applied": False,
        "post_guard_notice_context_used": True,
        "post_guard_context_source": "explicit_queue",
    }
    row.update(kw)
    return row


def run(ledgers, queues, previous=(), groups=()):
    return mod.merge(list(ledgers), list(queues), list(previous), [list(g) for g in groups], target_version=VERSION, accepted_at=NOW)


def test_matching_hash_accepts_and_removes_from_queue():
    state, remaining, summary = run([ledger()], [queue()], groups=[[result()]])
    assert len(state) == 1
    assert remaining == []
    assert state[0]["classification"] == "FIT"
    assert state[0]["lean_attractiveness"] == "HIGH"
    assert state[0]["business_calibration_version"] == BUSINESS_CALIBRATION_VERSION
    assert summary["stats"]["results_accepted"] == 1


def test_stale_hash_never_marks_updated_notice_classified():
    state, remaining, summary = run([ledger(h="NEW")], [queue(h="NEW")], groups=[[result(h="OLD")]])
    assert state == []
    assert len(remaining) == 1
    assert summary["rejected_result_reasons"]["stale_material_hash"] == 1


def test_parse_fallback_remains_in_queue():
    state, remaining, summary = run([ledger()], [queue()], groups=[[result(parse_error="request_error:TimeoutError")]])
    assert state == []
    assert len(remaining) == 1
    assert summary["rejected_result_reasons"]["parse_or_fallback_error"] == 1


def test_wrong_classifier_version_remains_in_queue():
    state, remaining, summary = run([ledger()], [queue()], groups=[[result(classifier_version="old-v0")]])
    assert state == []
    assert len(remaining) == 1
    assert summary["rejected_result_reasons"]["wrong_classifier_version"] == 1


def test_wrong_prompt_version_remains_in_queue():
    state, remaining, summary = run([ledger()], [queue()], groups=[[result(classifier_prompt_version="old-thin-prompt")]])
    assert state == []
    assert len(remaining) == 1
    assert summary["rejected_result_reasons"]["wrong_classifier_prompt_version"] == 1


def test_wrong_business_calibration_version_remains_in_queue():
    state, remaining, summary = run([ledger()], [queue()], groups=[[result(business_calibration_version="old-business-fit")]])
    assert state == []
    assert len(remaining) == 1
    assert summary["rejected_result_reasons"]["wrong_business_calibration_version"] == 1


def test_previous_valid_state_is_carried_without_new_inference():
    prev = mod.state_record(result(), NOW)
    state, remaining, summary = run([ledger()], [queue()], previous=[prev])
    assert len(state) == 1
    assert remaining == []
    assert summary["stats"]["previous_carried"] == 1
    assert summary["stats"]["queue_already_classified"] == 1


def test_previous_state_is_invalidated_when_material_changes():
    prev = mod.state_record(result(h="OLD"), NOW)
    state, remaining, summary = run([ledger(h="NEW")], [queue(h="NEW")], previous=[prev])
    assert state == []
    assert len(remaining) == 1
    assert summary["stats"]["previous_stale_dropped"] == 1


def test_previous_state_is_invalidated_when_business_calibration_changes():
    prev = mod.state_record(result(business_calibration_version="old-business-fit"), NOW)
    state, remaining, summary = run([ledger()], [queue()], previous=[prev])
    assert state == []
    assert len(remaining) == 1
    assert summary["stats"]["previous_wrong_business_calibration_dropped"] == 1


def test_conflicting_valid_results_are_requeued_not_resolved_by_order():
    first = result(classification="MAYBE", confidence=0.4)
    second = result(classification="FIT", confidence=0.8)
    state, remaining, summary = run([ledger()], [queue()], groups=[[first], [second]])
    assert state == []
    assert len(remaining) == 1
    assert summary["conflicting_candidate_ids"] == ["TED:1"]
    assert summary["stats"]["conflicting_candidates_requeued"] == 1
    assert summary["rejected_result_reasons"]["conflicting_valid_results"] == 2


def test_equivalent_duplicate_results_collapse_deterministically():
    first = result(classified_at_utc="2026-08-16T02:19:00+00:00", classifier_run_id="run-a")
    second = result(classified_at_utc="2026-08-16T02:20:00+00:00", classifier_run_id="run-b")
    state, remaining, summary = run([ledger()], [queue()], groups=[[first], [second]])
    assert remaining == []
    assert len(state) == 1
    assert state[0]["classifier_run_id"] == "run-b"
    assert summary["stats"]["duplicate_equivalent_candidates_collapsed"] == 1


def test_new_state_preserves_guard_and_selfheal_provenance():
    row = result(
        classifier_run_id="123",
        classifier_worker_id="7",
        initial_batch_size=8,
        effective_batch_size=4,
        self_heal_depth=1,
        recovered_after_split=True,
        deterministic_guard_actions=["physical_fit_to_maybe"],
        post_guard_actions=["possible_heavy_equipment_risk"],
        pre_post_guard_classification="STRONG_FIT",
    )
    state, remaining, _ = run([ledger()], [queue()], groups=[[row]])
    assert remaining == []
    saved = state[0]
    assert saved["classifier_run_id"] == "123"
    assert saved["classifier_worker_id"] == "7"
    assert saved["self_heal_depth"] == 1
    assert saved["recovered_after_split"] is True
    assert saved["deterministic_guard_actions"] == ["physical_fit_to_maybe"]
    assert saved["post_guard_actions"] == ["possible_heavy_equipment_risk"]
    assert saved["pre_post_guard_classification"] == "STRONG_FIT"
