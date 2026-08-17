from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from freshness_conveyor_watchdog import StageState, decide
from build_qwen_shadow_shards import freshness_rank
from build_qwen_dce_selection import freshness_rank as dce_freshness_rank
from materialize_dce_selection import build_candidate_index, canonical_candidate_id, resolve_candidate


def test_watchdog_repairs_stages_in_dependency_order():
    assert decide(StageState("42", "41", "41", "41")) == ("SNAPSHOT", "42")
    assert decide(StageState("42", "42", "41", "41")) == ("LEDGER", "42")
    assert decide(StageState("42", "42", "42", "41")) == ("QWEN", "42")
    assert decide(StageState("42", "42", "42", "42", 0)) == ("HEALTHY", "42")


def test_watchdog_keeps_qwen_hot_while_residual_queue_remains():
    assert decide(StageState("42", "42", "42", "42", 38113)) == ("QWEN", "42")


def test_watchdog_never_advances_without_usable_discovery():
    assert decide(StageState(None, "41", "41", "41")) == ("WAIT_NO_USABLE_DISCOVERY", None)


def test_qwen_current_material_changes_preempt_backfill():
    now = datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc)
    assert freshness_rank({"queue_reason": "NEW"}, now=now) == 0
    assert freshness_rank({"queue_reason": "UPDATED"}, now=now) == 0
    assert freshness_rank({"queue_reason": "CLASSIFIER_VERSION_OR_UNCLASSIFIED", "first_seen_at": (now - timedelta(hours=4)).isoformat()}, now=now) == 1
    assert freshness_rank({"queue_reason": "CLASSIFIER_VERSION_OR_UNCLASSIFIED", "first_seen_at": (now - timedelta(hours=40)).isoformat()}, now=now) == 2


def test_recent_notice_stays_fresh_after_next_ledger_generation():
    now = datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc)
    row = {
        "queue_reason": "CLASSIFIER_VERSION_OR_UNCLASSIFIED",
        "first_seen_at": (now - timedelta(hours=23, minutes=59)).isoformat(),
    }
    assert freshness_rank(row, now=now, fresh_hours=24) == 1


def test_dce_shortlist_preserves_same_freshness_order():
    now = datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc)
    assert dce_freshness_rank({"ledger_event": "NEW"}, now=now) == 0
    assert dce_freshness_rank({"ledger_event": "UPDATED"}, now=now) == 0
    assert dce_freshness_rank({"ledger_event": "UNCHANGED", "first_seen_at": (now - timedelta(hours=3)).isoformat()}, now=now) == 1
    assert dce_freshness_rank({"ledger_event": "UNCHANGED", "first_seen_at": (now - timedelta(days=2)).isoformat()}, now=now) == 2


def test_qwen_to_dce_candidate_identity_is_case_insensitive():
    candidates = [{"candidate_id": "UK_PCS_OCDS:ocds-r6ebe6-0000839484", "title": "Example"}]
    indexed = build_candidate_index(candidates)
    qwen_id = "uk_pcs_ocds:ocds-r6ebe6-0000839484"
    matches = indexed[canonical_candidate_id(qwen_id)]
    assert len(matches) == 1
    assert matches[0]["candidate_id"] == candidates[0]["candidate_id"]


def test_qwen_ocid_resolves_release_level_discovery_candidate():
    candidates = [{
        "candidate_id": "UK_PCS_OCDS:release-2026-08-17-123",
        "source": "UK_PCS_OCDS",
        "ocid": "ocds-r6ebe6-0000839484",
        "title": "Digital communications support",
        "buyer": "Example Council",
        "deadline": "2026-08-30T12:00:00+00:00",
    }]
    indexed = build_candidate_index(candidates)
    selection = {"candidate_id": "uk_pcs_ocds:ocds-r6ebe6-0000839484", "qwen": {}}
    resolved, reason = resolve_candidate(selection, indexed)
    assert resolved is candidates[0]
    assert reason == "source_alias"
