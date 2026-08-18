from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from qwen_notice_post_guard import guard


def base(
    title: str,
    *,
    classification: str = "REJECT_OBVIOUS",
    survival: str = "KEEP",
    flags=None,
    lean: str = "LOW",
    route: str = "UNCLEAR",
):
    return {
        "canonical_notice_id": "X:1",
        "classification": classification,
        "lean_attractiveness": lean,
        "delivery_mode": route,
        "friction_flags": list(flags or []),
        "needs_gpt_review": False,
        "survival_decision": survival,
        "dce_eligible": False,
        "business_calibration_version": "spm-business-fit-v2",
        "notice": {"title": title, "description": ""},
    }


def test_core_model_reject_is_rescued_to_fit_without_finalizing_truth():
    out = guard(base("Animation and Software Development for a public visitor experience"))
    assert out["classification"] == "FIT"
    assert out["delivery_mode"] == "DIRECT_DIGITAL"
    assert out["dce_eligible"] is True
    assert out["needs_gpt_review"] is True
    assert "high_recall_core_reject_rescued_to_fit" in out["post_guard_actions"]
    assert out["business_calibration_version"] == "spm-business-fit-v2"


def test_clear_web_application_reject_is_rescued_to_fit():
    out = guard(base("Design and development of an accessible web application"))
    assert out["classification"] == "FIT"
    assert out["delivery_mode"] == "DIRECT_DIGITAL"


def test_high_lean_direct_core_maybe_is_promoted_to_fit():
    out = guard(base(
        "Design and development of an accessible web application",
        classification="MAYBE",
        lean="HIGH",
        route="DIRECT_DIGITAL",
    ))
    assert out["classification"] == "FIT"
    assert out["dce_eligible"] is True
    assert "high_recall_core_high_direct_maybe_promoted_to_fit" in out["post_guard_actions"]


def test_maybe_not_promoted_when_any_confidence_leg_is_missing():
    not_high = guard(base("Website development", classification="MAYBE", lean="MEDIUM", route="DIRECT_DIGITAL"))
    not_direct = guard(base("Website development", classification="MAYBE", lean="HIGH", route="UNCLEAR"))
    not_core = guard(base("General consultancy", classification="MAYBE", lean="HIGH", route="DIRECT_DIGITAL"))
    assert not_high["classification"] == "MAYBE"
    assert not_direct["classification"] == "MAYBE"
    assert not_core["classification"] == "MAYBE"


def test_brokerable_goods_reject_is_preserved_as_maybe_not_erased():
    out = guard(base("Supply of commercial spare parts and components"))
    assert out["classification"] == "MAYBE"
    assert out["delivery_mode"] == "BROKER_RESELL"
    assert out["needs_gpt_review"] is True


def test_survival_drop_is_never_rescued_even_for_digital_words():
    out = guard(base("Website development request for information", survival="DROP"))
    assert out["classification"] == "REJECT_OBVIOUS"
    assert out["dce_eligible"] is False
    assert not any("rescued" in x for x in out["post_guard_actions"])


def test_hard_regulated_friction_is_never_rescued():
    out = guard(base("Software and regulated pharmaceutical supplies", flags=["REGULATED_GOODS"]))
    assert out["classification"] == "REJECT_OBVIOUS"
    assert out["dce_eligible"] is False
    assert not any("rescued" in x for x in out["post_guard_actions"])
