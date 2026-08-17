from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from final_verdict_guard import apply_post_dce_scope_guard
from post_dce_scope_gate import evaluate_post_dce_scope


def gate_ready_review(title: str, deliverables=None):
    return {
        "candidate_id": "TEST:X",
        "title": title,
        "classification": "MODEL_REVIEW_REQUIRED",
        "evidence_quality": {
            "content_quality": "SUBSTANTIVE_DCE_PRESENT",
            "gate_readiness": True,
        },
        "gate_evidence_candidates": {
            "deliverables_scope": deliverables or [],
        },
    }


def test_hvac_replacement_auto_red():
    rec = gate_ready_review("Replace HVAC Units at Outlying Clinic")
    assert apply_post_dce_scope_guard(rec) is True
    assert rec["classification"] == "RED"
    assert "NO_SCOPE_PHYSICAL_HVAC_WORKS" in rec["deterministic_scope_reject"]["reason_codes"]


def test_hvac_supply_remains_brokerable():
    rec = gate_ready_review("Supply and delivery of HVAC units")
    assert evaluate_post_dce_scope(rec)["auto_reject"] is False
    assert apply_post_dce_scope_guard(rec) is False
    assert rec["classification"] == "MODEL_REVIEW_REQUIRED"


def test_construction_auto_red():
    rec = gate_ready_review("Rochester Courthouse Construction")
    assert apply_post_dce_scope_guard(rec) is True
    assert rec["classification"] == "RED"
    assert "NO_SCOPE_PHYSICAL_CONSTRUCTION_WORKS" in rec["deterministic_scope_reject"]["reason_codes"]


def test_building_renovation_auto_red():
    rec = gate_ready_review("Federal Building Renovation Works")
    assert apply_post_dce_scope_guard(rec) is True
    assert rec["classification"] == "RED"


def test_dredging_auto_red():
    rec = gate_ready_review("Dredging and sediment disposal services")
    assert apply_post_dce_scope_guard(rec) is True
    assert rec["classification"] == "RED"
    assert "NO_SCOPE_PHYSICAL_DREDGING" in rec["deterministic_scope_reject"]["reason_codes"]


def test_design_build_water_infrastructure_auto_red():
    rec = gate_ready_review("Design-build water supply storage system for Bazum Village")
    assert apply_post_dce_scope_guard(rec) is True
    assert rec["classification"] == "RED"
    assert "NO_SCOPE_PHYSICAL_DESIGN_BUILD_INFRASTRUCTURE" in rec["deterministic_scope_reject"]["reason_codes"]


def test_barnagh_like_webar_scope_survives():
    rec = gate_ready_review(
        "Greenway Hub interpretive experience",
        [{"text": "Animation, augmented reality WebAR experience and QR codes for visitors."}],
    )
    result = evaluate_post_dce_scope(rec)
    assert result["auto_reject"] is False
    assert result["digital_override"] is True
    assert apply_post_dce_scope_guard(rec) is False


def test_digital_building_automation_scope_survives():
    rec = gate_ready_review(
        "Modernize Building Automated Systems",
        [{"text": "Provide building automation software, BAS analytics and controls analytics."}],
    )
    result = evaluate_post_dce_scope(rec)
    assert result["auto_reject"] is False
    assert result["digital_override"] is True


def test_general_commodity_supply_remains_brokerable():
    rec = gate_ready_review("Supply and delivery of valves and generators")
    assert evaluate_post_dce_scope(rec)["auto_reject"] is False
    assert apply_post_dce_scope_guard(rec) is False


def test_direct_shard_gate_evidence_schema_is_used():
    rec = gate_ready_review(
        "Mechanical works procurement",
        [{"text": "The contractor shall replace HVAC units and perform installation."}],
    )
    result = evaluate_post_dce_scope(rec)
    assert result["auto_reject"] is True
    assert "NO_SCOPE_PHYSICAL_HVAC_WORKS" in result["reason_codes"]
