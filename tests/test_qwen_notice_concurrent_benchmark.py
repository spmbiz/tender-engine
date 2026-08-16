from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "pipeline" / "qwen_notice_concurrent_benchmark.py"
spec = importlib.util.spec_from_file_location("qwen_concurrent", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def envelope(cid="TED:1"):
    return {
        "canonical_notice_id": cid,
        "material_fields_hash": "abc123",
        "notice": {
            "candidate_id": cid,
            "title": "Website redesign",
            "description": "Accessible website and CMS implementation",
        },
    }


def test_fallback_is_maybe_and_preserves_identity():
    x = mod.fallback("TED:1", envelope(), "future_error:TimeoutError", 1800, "ledger-1")
    assert x["canonical_notice_id"] == "TED:1"
    assert x["classification"] == "MAYBE"
    assert x["delivery_mode"] == "UNCLEAR"
    assert x["input_material_fields_hash"] == "abc123"
    assert x["source_ledger_generation"] == "ledger-1"


def test_concurrent_contract_reuses_v2_classifier_version():
    assert "concurrent-slots" in mod.fallback("TED:1", envelope(), "x", 1800, "ledger-1")["classifier_version"]
