from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "pipeline" / "qwen_notice_shadow_classifier.py"
spec = importlib.util.spec_from_file_location("qwen_shadow", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def envelope(cid: str, title: str = "Website redesign") -> dict:
    return {
        "canonical_notice_id": cid,
        "notice": {
            "candidate_id": cid,
            "source": "TED",
            "country": "IE",
            "buyer": "Buyer",
            "title": title,
            "description": "Accessible website design and implementation",
        },
    }


def test_invalid_json_falls_back_to_maybe():
    assert mod.extract_object("not json") is None
    out = mod.normalize(None, "invalid_json")
    assert out["classification"] == "MAYBE"
    assert out["confidence"] == 0.0
    assert out["novelty_or_unusual_flag"] is True
    assert out["delivery_mode"] == "UNCLEAR"


def test_unknown_classification_never_becomes_reject():
    out = mod.normalize({
        "classification": "NOPE",
        "confidence": 0.99,
        "delivery_mode": "DIRECT_DIGITAL",
        "reason": "bad enum",
    })
    assert out["classification"] == "MAYBE"
    assert out["parse_error"] == "invalid_classification"


def test_valid_reject_is_preserved_but_only_as_shadow_output():
    out = mod.normalize({
        "classification": "REJECT_OBVIOUS",
        "confidence": 0.94,
        "novelty_or_unusual_flag": False,
        "delivery_mode": "UNCLEAR",
        "reason": "Pure heavy civil works with no plausible lean delivery path.",
    })
    assert out["classification"] == "REJECT_OBVIOUS"
    assert out["confidence"] == 0.94


def test_json_object_can_be_recovered_from_wrapped_model_text():
    obj = mod.extract_object('Result:\n{"classification":"FIT","confidence":0.8}\nDone')
    assert obj == {"classification": "FIT", "confidence": 0.8}


def test_deterministic_sample_is_stable_independent_of_input_order():
    rows = [envelope(f"TED:{i}") for i in range(30)]
    a = [mod.candidate_id(x) for x in mod.deterministic_sample(rows, 8)]
    b = [mod.candidate_id(x) for x in mod.deterministic_sample(list(reversed(rows)), 8)]
    assert a == b
    assert len(a) == 8
    assert len(set(a)) == 8


def test_compact_notice_truncates_large_description():
    row = envelope("TED:large")
    row["notice"]["description"] = "x" * 6000
    compact = mod.compact_notice(row)
    assert len(compact["description"]) < 5100
    assert compact["description"].endswith("…[truncated]")
