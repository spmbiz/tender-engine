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
        "classifier_prompt_version": "p1",
        "classifier_version": VERSION,
        "business_calibration_version": BUSINESS_CALIBRATION_VERSION,
        "classification": "FIT",
        "confidence": 0.9,
        "lean_attractiveness": "HIGH",
        "delivery_mode": "DIRECT_DIGITAL",
        "friction_flags": [],
        "classified_at_utc": NOW,
        "parse_error": None,
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
    assert summary["results_accepted"] == 1 if "results_accepted" in summary else summary["stats"]["results_accepted"] == 1


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


def test_later_result_group_replaces_same_hash_state_deterministically():
    first = result(classification="MAYBE", confidence=0.4)
    second = result(classification="FIT", confidence=0.8)
    state, remaining, _ = run([ledger()], [queue()], groups=[[first], [second]])
    assert remaining == []
    assert state[0]["classification"] == "FIT"
    assert state[0]["confidence"] == 0.8
