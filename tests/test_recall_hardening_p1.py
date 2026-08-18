from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))


def test_ted_requests_and_persists_buyer_country():
    text = (ROOT / "pipeline/discover_ted.py").read_text(encoding="utf-8")
    assert '"buyer-country"' in text
    assert 'buyer_country = scalar(first_field(item, "buyer-country"))' in text
    assert '"country": str(buyer_country or "") or None' in text


def test_snapshot_uses_explicit_country_before_source_fallback():
    from build_live_world_snapshot import make_row

    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    explicit, _ = make_row(
        {"candidate_id": "TED:1-2026", "source": "TED", "country": "BE", "title": "x"},
        now,
    )
    assert explicit["country"] == "BE"

    fallback, _ = make_row(
        {"candidate_id": "US-SAM:abc", "source": "US_SAM_BULK", "title": "x"},
        now,
    )
    assert fallback["country"] == "US"

    scotland, _ = make_row(
        {"candidate_id": "PCS:abc", "source": "UK_PCS_OCDS", "title": "x"},
        now,
    )
    assert scotland["country"] == "GB"


def test_qwen_rich_context_preserves_tail_and_gate_fields():
    import qwen_notice_batch_selfheal_rich as rich

    row = {
        "canonical_notice_id": "X",
        "notice": {
            "description": "HEAD " + ("middle " * 800) + "TAIL_CONSTRAINT_TOKEN",
            "notice_eligibility": "ELIGIBILITY_TOKEN",
            "subcontracting": "SUBCONTRACT_TOKEN",
            "lots": "LOTS_TOKEN",
            "award_criteria": "AWARD_TOKEN",
        },
    }
    text = rich.rich_description(row, 500)
    assert len(text) <= rich.MIN_CONTEXT_CHARS + 8
    assert rich.MIN_CONTEXT_CHARS >= 2200
    assert "HEAD" in text
    assert "TAIL_CONSTRAINT_TOKEN" in text
    assert "ELIGIBILITY_TOKEN" in text
    assert "SUBCONTRACT_TOKEN" in text


def test_live_qwen_entrypoint_uses_rich_wrapper():
    wrapper = (ROOT / "pipeline/qwen_notice_batch_selfheal.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/qwen-live-classification.yml").read_text(encoding="utf-8")
    assert "qwen_notice_batch_selfheal_rich" in wrapper
    assert "pipeline/qwen_notice_batch_selfheal.py" in workflow
