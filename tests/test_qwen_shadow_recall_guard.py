from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "pipeline" / "qwen_shadow_recall_guard.py"
spec = importlib.util.spec_from_file_location("qwen_guard", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def row(title, classification="STRONG_FIT", mode="DIRECT_DIGITAL", description=""):
    return {
        "classification": classification,
        "delivery_mode": mode,
        "notice": {"title": title, "description": description},
    }


def test_truck_is_kept_but_not_strong_direct_digital():
    x = mod.apply_guard(row("2-Achs LKW Allradantrieb inkl. Aufbau"))
    assert x["classification"] == "FIT"
    assert x["delivery_mode"] == "BROKER_RESELL"
    assert x["model_classification"] == "STRONG_FIT"


def test_parts_reject_is_rescued_for_broker_recall():
    x = mod.apply_guard(row("LIVOS TECHNOLOGIES / DOMETIC PARTS", "REJECT_OBVIOUS", "UNCLEAR"))
    assert x["classification"] == "MAYBE"
    assert x["delivery_mode"] == "BROKER_RESELL"


def test_regulated_drug_never_ranks_strong_from_notice_only():
    x = mod.apply_guard(row("Methylphenidate HCL IR"))
    assert x["classification"] == "MAYBE"
    assert x["delivery_mode"] == "BROKER_RESELL"


def test_hvac_is_subcontractable_not_direct_digital():
    x = mod.apply_guard(row("Heating, ventilation and air-conditioning installation work", "FIT", "DIRECT_DIGITAL"))
    assert x["classification"] == "FIT"
    assert x["delivery_mode"] == "SUBCONTRACTABLE"


def test_real_digital_scope_remains_strong_direct():
    x = mod.apply_guard(row("Animation and Software Development", "STRONG_FIT", "DIRECT_DIGITAL", "WebAR mobile application and animation software"))
    assert x["classification"] == "STRONG_FIT"
    assert x["delivery_mode"] == "DIRECT_DIGITAL"
    assert x["recall_guard_applied"] is False


def test_personal_services_reject_can_remain_reject():
    x = mod.apply_guard(row("Aviation Security Officer - Personal Services Contract", "REJECT_OBVIOUS", "UNCLEAR"))
    assert x["classification"] == "REJECT_OBVIOUS"


def test_indirect_path_downgrades_reject_to_maybe_without_dropping():
    x = mod.apply_guard(row("Specialist technical service", "REJECT_OBVIOUS", "UNCLEAR", "Subcontractors may be used"))
    assert x["classification"] == "MAYBE"
    assert x["recall_guard_applied"] is True
