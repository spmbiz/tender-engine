from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "pipeline" / "build_notice_intelligence_ledger.py"
spec = importlib.util.spec_from_file_location("notice_ledger", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def notice(cid="TED:1", **overrides):
    row = {
        "candidate_id": cid,
        "source_family": "EU",
        "source": "TED",
        "country": "IE",
        "buyer": "Buyer",
        "title": "Website redesign",
        "description": "Design and build an accessible public website",
        "cpv_or_category": "72413000",
        "estimated_value": 50000,
        "currency": "EUR",
        "publication_date": "2026-08-15",
        "deadline": "2026-09-01T10:00:00Z",
        "deadline_utc": "2026-09-01T10:00:00Z",
        "open_state": "OPEN_CONFIRMED",
        "procedure": "open",
        "lots": None,
        "notice_eligibility": None,
        "award_criteria": None,
        "subcontracting": None,
        "urls": ["https://example.test/tender/1"],
    }
    row.update(overrides)
    return row


def run(current, previous=(), now="2026-08-16T01:00:00+00:00", version="qwen-shadow-v1"):
    return mod.build(current, previous, now=now, target_classifier_version=version)


def test_first_seen_is_new_and_change_queued():
    ledger, changes, classq, summary = run([notice()])
    assert ledger[0]["ledger_event"] == "NEW"
    assert ledger[0]["needs_reclassification"] is True
    assert len(changes) == 1
    assert len(classq) == 1
    assert summary["new"] == 1


def test_unchanged_notice_does_not_enter_change_queue():
    ledger1, _, _, _ = run([notice()])
    # Simulate Qwen having classified the first backfill.
    ledger1[0]["classification"] = "FIT"
    ledger1[0]["classifier_version"] = "qwen-shadow-v1"
    ledger2, changes, classq, summary = run(
        [notice()], ledger1, now="2026-08-16T02:00:00+00:00"
    )
    assert ledger2[0]["ledger_event"] == "UNCHANGED"
    assert ledger2[0]["first_seen_at"] == ledger1[0]["first_seen_at"]
    assert ledger2[0]["needs_reclassification"] is False
    assert changes == []
    assert classq == []
    assert summary["unchanged"] == 1


def test_deadline_change_is_material_update_and_requeued():
    ledger1, _, _, _ = run([notice()])
    ledger1[0]["classification"] = "FIT"
    ledger1[0]["classifier_version"] = "qwen-shadow-v1"
    changed = notice(deadline="2026-09-03T10:00:00Z", deadline_utc="2026-09-03T10:00:00Z")
    ledger2, changes, classq, summary = run(
        [changed], ledger1, now="2026-08-16T02:00:00+00:00"
    )
    assert ledger2[0]["ledger_event"] == "UPDATED"
    assert ledger2[0]["first_seen_at"] == ledger1[0]["first_seen_at"]
    assert ledger2[0]["previous_material_fields_hash"] == ledger1[0]["material_fields_hash"]
    assert ledger2[0]["classification_stale"] is True
    assert len(changes) == 1
    assert len(classq) == 1
    assert summary["updated"] == 1


def test_derived_open_state_change_is_non_material():
    ledger1, _, _, _ = run([notice(open_state="OPEN_UNVERIFIED")])
    ledger1[0]["classification"] = "FIT"
    ledger1[0]["classifier_version"] = "qwen-shadow-v1"
    ledger2, changes, classq, _ = run(
        [notice(open_state="OPEN_CONFIRMED")], ledger1, now="2026-08-16T02:00:00+00:00"
    )
    assert ledger2[0]["ledger_event"] == "UNCHANGED"
    assert changes == []
    assert classq == []


def test_same_title_different_source_ids_are_never_fuzzy_merged():
    a = notice("TED:1")
    b = notice("IE:1", source="IRELAND_ETENDERS", urls=["https://example.test/ie/1"])
    ledger, changes, _, summary = run([a, b])
    assert len(ledger) == 2
    assert len(changes) == 2
    assert summary["current_unique"] == 2


def test_classifier_version_bump_requeues_without_material_change():
    ledger1, _, _, _ = run([notice()])
    ledger1[0]["classification"] = "FIT"
    ledger1[0]["classifier_version"] = "qwen-shadow-v1"
    ledger2, changes, classq, _ = run(
        [notice()], ledger1, now="2026-08-16T02:00:00+00:00", version="qwen-shadow-v2"
    )
    assert ledger2[0]["ledger_event"] == "UNCHANGED"
    assert changes == []
    assert len(classq) == 1
    assert classq[0]["queue_reason"] == "CLASSIFIER_VERSION_OR_UNCLASSIFIED"
