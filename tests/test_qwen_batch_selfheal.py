from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


mod = load("qwen_selfheal", "pipeline/qwen_notice_batch_selfheal.py")


def envelope(cid, title, description=""):
    return {"canonical_notice_id": cid, "notice": {"candidate_id": cid, "title": title, "description": description}}


def test_extract_compact_object_items():
    x = mod.extract_items('{"x":[{"i":"A","d":"F","l":"H","r":"D","f":[],"n":0,"g":0}]}')
    assert x and x[0]["i"] == "A"


def test_regulated_guard_keeps_row_but_caps_lean():
    decoded = mod.decode_item({"i":"A","d":"S","l":"H","r":"D","f":[],"n":0,"g":0})
    out, actions = mod.deterministic_guard(decoded, envelope("A", "Methylphenidate HCL IR"))
    assert out["classification"] == "MAYBE"
    assert out["lean_attractiveness"] == "LOW"
    assert out["delivery_mode"] == "BROKER_RESELL"
    assert "REGULATED_GOODS" in out["friction_flags"]
    assert actions


def test_physical_model_reject_is_preserved_for_post_guard_recall():
    decoded = mod.decode_item({"i":"A","d":"R","l":"H","r":"D","f":[],"n":0,"g":0})
    out, _ = mod.deterministic_guard(decoded, envelope("A", "Commercial truck parts"))
    assert out["classification"] == "REJECT_OBVIOUS"
    assert out["delivery_mode"] == "BROKER_RESELL"
    assert out["lean_attractiveness"] == "MEDIUM"
    assert out["dce_eligible"] is False
    assert out["business_calibration_version"] == "spm-business-fit-v2"


def test_digital_model_reject_is_preserved_for_post_guard_recall():
    decoded = mod.decode_item({"i":"A","d":"R","l":"M","r":"U","f":[],"n":0,"g":1})
    out, actions = mod.deterministic_guard(decoded, envelope("A", "Website redesign and CMS migration"))
    assert out["classification"] == "REJECT_OBVIOUS"
    assert out["dce_eligible"] is False
    assert "clear_digital_floor_fit" not in actions
    assert out["business_calibration_version"] == "spm-business-fit-v2"
