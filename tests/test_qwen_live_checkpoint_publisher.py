from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from qwen_live_checkpoint_publisher import (
    checkpoint_path_for,
    guarded_checkpoint_rows,
    load_exact_context,
    write_jsonl_atomic,
)


def raw_result(candidate: str = "X:1") -> dict:
    return {
        "schema": "QWEN_NOTICE_BATCH_SELFHEAL_V1",
        "canonical_notice_id": candidate,
        "input_material_fields_hash": "h1",
        "classifier_model": "Qwen3-4B-GGUF",
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": "qwen-batch-high-recall-business-fit-v3-rich",
        "classifier_version": "qwen3-4b-q4km-batch-selfheal-v1",
        "classification": "MAYBE",
        "confidence": 0.8,
        "lean_attractiveness": "HIGH",
        "delivery_mode": "DIRECT_DIGITAL",
        "friction_flags": [],
        "unusual_or_novel": False,
        "needs_gpt_review": False,
        "survival_decision": "KEEP",
        "dce_eligible": True,
        "business_calibration_version": "spm-business-fit-v2",
        "parse_error": None,
    }


def test_exact_context_checkpoint_is_post_guarded_before_transport(tmp_path: Path):
    queue = tmp_path / "shard.jsonl.gz"
    with gzip.open(queue, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "canonical_notice_id": "X:1",
            "material_fields_hash": "h1",
            "notice": {
                "candidate_id": "X:1",
                "title": "Design and development of an accessible web application",
                "description": "Responsive public web application and CMS services",
            },
        }) + "\n")
    context = load_exact_context(queue)
    rows = guarded_checkpoint_rows([raw_result()], context)
    assert len(rows) == 1
    row = rows[0]
    assert row["canonical_notice_id"] == "X:1"
    assert row["classification"] == "FIT"
    assert row["post_guard_notice_context_used"] is True
    assert row["post_guard_context_source"] == "worker_live_checkpoint_exact_shard"
    assert str(row["post_guard_schema"]).startswith("QWEN_NOTICE_POST_GUARD_V5_")
    assert row["input_material_fields_hash"] == "h1"
    assert row["classifier_prompt_version"] == "qwen-batch-high-recall-business-fit-v3-rich"
    assert row["business_calibration_version"] == "spm-business-fit-v2"


def test_missing_exact_context_fails_closed():
    with pytest.raises(ValueError, match="missing exact checkpoint context"):
        guarded_checkpoint_rows([raw_result("X:missing")], {})


def test_duplicate_checkpoint_candidate_fails_closed():
    context = {"X:1": {"candidate_id": "X:1", "title": "Website development"}}
    with pytest.raises(ValueError, match="duplicate raw checkpoint candidate"):
        guarded_checkpoint_rows([raw_result(), raw_result()], context)


def test_checkpoint_path_is_worker_scoped():
    assert checkpoint_path_for(Path("qwen-live-7-raw.jsonl")).name == "qwen-live-7-guarded-checkpoint.jsonl"


def test_atomic_checkpoint_writer_conserves_rows(tmp_path: Path):
    path = tmp_path / "checkpoint.jsonl"
    rows = [raw_result("X:1"), raw_result("X:2")]
    assert write_jsonl_atomic(path, rows) == 2
    decoded = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [r["canonical_notice_id"] for r in decoded] == ["X:1", "X:2"]
