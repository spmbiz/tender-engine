from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from build_fresh_digital_express import build


def row(cid: str, *, title: str, reason: str = "NEW", hours: int = 120, material_hash: str = "h1", portal: str = "IRELAND_ETENDERS"):
    now = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
    return {
        "canonical_notice_id": cid,
        "material_fields_hash": material_hash,
        "queue_reason": reason,
        "notice": {
            "candidate_id": cid,
            "portal": portal,
            "source": portal,
            "title": title,
            "buyer": "Test Buyer",
            "description": "Public procurement requirement",
            "deadline": (now + timedelta(hours=hours)).isoformat(),
        },
    }


def run_build(rows, tmp_path: Path, *, attempts: list[dict] | None = None):
    attempt_path = tmp_path / "attempts.jsonl"
    if attempts:
        attempt_path.write_text("".join(json.dumps(x) + "\n" for x in attempts), encoding="utf-8")
    now = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
    return build(rows, source_run="123456789", attempts_path=attempt_path, limit=48, min_score=84, now=now)


def test_fresh_title_level_website_enters_express(tmp_path):
    out, summary = run_build([row("IE:1", title="Website redesign and development services")], tmp_path)
    assert [x["candidate_id"] for x in out] == ["IE:1"]
    assert out[0]["selection_bucket"] == "fresh-digital-express"
    assert out[0]["status"] == "AUTO_DCE_PREFETCH"
    assert summary["safety"]["express_lane_can_create_green"] is False
    assert summary["safety"]["authoritative_dce_required_downstream"] is True


def test_historical_and_expired_rows_do_not_enter_but_are_not_deleted(tmp_path):
    rows = [
        row("IE:hist", title="Website redesign and development services", reason="UNCHANGED"),
        row("IE:late", title="Website redesign and development services", hours=1),
    ]
    out, summary = run_build(rows, tmp_path)
    assert out == []
    assert summary["counts"]["skip_not_new_or_updated"] == 1
    assert summary["counts"]["skip_expired_or_too_late"] == 1
    assert summary["safety"]["drops_or_deletes_notices"] is False
    assert summary["safety"]["semantic_qwen_lane_remains_independent"] is True


def test_obvious_physical_not_promoted_by_description_boilerplate(tmp_path):
    r = row("IE:physical", title="Supply of industrial pumps and valves")
    r["notice"]["description"] = "Supplier must maintain a website for contract notices."
    out, summary = run_build([r], tmp_path)
    assert out == []
    assert summary["counts"]["skip_not_express_core"] == 1


def test_preliminary_market_consultation_never_enters_express(tmp_path):
    r = row("IE:pmc", title="Preliminary Market Consultation - Digital Marketing Expertise")
    out, summary = run_build([r], tmp_path)
    assert out == []
    assert summary["counts"]["skip_obvious_non_bid"] == 1
    assert summary["safety"]["obvious_non_bid_notices_excluded_from_express_only"] is True
    assert summary["safety"]["semantic_qwen_lane_remains_independent"] is True


def test_exact_material_version_attempted_is_skipped(tmp_path):
    attempts = [{
        "candidate_id": "IE:1",
        "material_fields_hash": "h1",
        "source_run_id": "123456789",
        "attempt_status": "DCE_RUN_SUCCESS_MATERIALIZED",
    }]
    out, summary = run_build([row("IE:1", title="Website redesign and development services", material_hash="h1")], tmp_path, attempts=attempts)
    assert out == []
    assert summary["counts"]["skip_exact_version_attempted"] == 1


def test_updated_material_hash_is_allowed_back_after_prior_attempt(tmp_path):
    attempts = [{
        "candidate_id": "IE:1",
        "material_fields_hash": "old-hash",
        "source_run_id": "111111111",
        "attempt_status": "DCE_RUN_SUCCESS_MATERIALIZED",
    }]
    out, _ = run_build([row("IE:1", title="Website redesign and development services", reason="UPDATED", material_hash="new-hash")], tmp_path, attempts=attempts)
    assert [x["candidate_id"] for x in out] == ["IE:1"]


def test_limit_is_bounded_and_prefers_higher_score_then_urgency(tmp_path):
    rows = [
        row("IE:generic", title="Website services", hours=200),
        row("IE:strong", title="Website redesign and development services", hours=200),
        row("IE:urgent", title="Website redesign and development services", hours=60),
    ]
    now = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
    out, _ = build(rows, source_run="123", attempts_path=None, limit=1, min_score=84, now=now)
    assert len(out) == 1
    assert out[0]["candidate_id"] == "IE:urgent"
