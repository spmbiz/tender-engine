from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from freshness_conveyor_watchdog import StageState, decide
from build_qwen_shadow_shards import freshness_rank


def test_watchdog_repairs_stages_in_dependency_order():
    assert decide(StageState("42", "41", "41", "41")) == ("SNAPSHOT", "42")
    assert decide(StageState("42", "42", "41", "41")) == ("LEDGER", "42")
    assert decide(StageState("42", "42", "42", "41")) == ("QWEN", "42")
    assert decide(StageState("42", "42", "42", "42")) == ("HEALTHY", "42")


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
