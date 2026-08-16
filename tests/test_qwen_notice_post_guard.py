from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qwen_post_guard", ROOT / "pipeline/qwen_notice_post_guard.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def row(title, classification="STRONG_FIT", lean="HIGH", flags=None):
    return {
        "canonical_notice_id": "X",
        "classification": classification,
        "lean_attractiveness": lean,
        "friction_flags": list(flags or []),
        "needs_gpt_review": False,
        "notice": {"t": title, "d": ""},
    }


def test_personal_service_is_capped_without_deletion():
    out = mod.guard(row("Aviation Security Officer — Personal Services Contract"))
    assert out["classification"] == "MAYBE"
    assert out["lean_attractiveness"] == "LOW"
    assert out["needs_gpt_review"] is True
    assert "LICENSED_PERSONNEL" in out["friction_flags"]


def test_truck_gets_possible_heavy_equipment_risk():
    out = mod.guard(row("Supply of commercial trucks"))
    assert out["classification"] == "FIT"
    assert out["lean_attractiveness"] == "MEDIUM"
    assert "HEAVY_EQUIPMENT" in out["friction_flags"]


def test_microscope_gets_possible_heavy_equipment_risk():
    out = mod.guard(row("Supply of laboratory microscopes", classification="FIT", lean="MEDIUM"))
    assert out["classification"] == "FIT"
    assert "HEAVY_EQUIPMENT" in out["friction_flags"]


def test_unrelated_digital_row_is_unchanged_commercially():
    original = row("Website redesign", classification="FIT", lean="HIGH")
    out = mod.guard(original)
    assert out["classification"] == "FIT"
    assert out["lean_attractiveness"] == "HIGH"
    assert out["friction_flags"] == []
    assert out["post_guard_applied"] is False
