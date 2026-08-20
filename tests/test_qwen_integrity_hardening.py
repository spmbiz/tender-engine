from __future__ import annotations

import gzip
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import qwen_notice_batch_selfheal_rich as rich
import qwen_notice_post_guard as post_guard


def test_post_guard_understands_compact_category_and_procedure_aliases():
    row = {
        "canonical_notice_id": "X:1",
        "classification": "STRONG_FIT",
        "lean_attractiveness": "HIGH",
        "delivery_mode": "UNCLEAR",
        "friction_flags": [],
        "survival_decision": "KEEP",
        "notice": {
            "t": "Supply requirement",
            "d": "",
            "k": "laboratory microscopes and scientific instruments",
            "p": "open procedure",
        },
    }
    out = post_guard.guard(row)
    assert out["classification"] == "FIT"
    assert "HEAVY_EQUIPMENT" in out["friction_flags"]
    assert "possible_heavy_equipment_risk" in out["post_guard_actions"]


def test_auto_discovery_recovers_exact_source_context_from_live_shards(tmp_path: Path):
    root = tmp_path / "work" / "shards"
    root.mkdir(parents=True)
    shard = root / "qwen-shadow-123-shard-000-of-002.jsonl.gz"
    with gzip.open(shard, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "candidate_id": "TED:abc",
            "title": "Generic procurement",
            "description": "Full source says website development and CMS implementation",
            "cpv_or_category": "software development",
            "procedure": "open",
        }) + "\n")
        fh.write(json.dumps({"candidate_id": "TED:other", "title": "Other"}) + "\n")

    context, file_count = post_guard.discover_notice_context(root, {"TED:abc"})
    assert file_count == 1
    assert set(context) == {"TED:abc"}
    raw = {
        "canonical_notice_id": "TED:abc",
        "classification": "MAYBE",
        "lean_attractiveness": "HIGH",
        "delivery_mode": "DIRECT_DIGITAL",
        "friction_flags": [],
        "survival_decision": "KEEP",
    }
    out = post_guard.guard(raw, context["TED:abc"], context_source="auto_discovered_queue")
    assert out["classification"] == "FIT"
    assert out["post_guard_notice_context_used"] is True
    assert out["post_guard_context_source"] == "auto_discovered_queue"


def test_auto_discovery_duplicate_identity_fails_closed(tmp_path: Path):
    root = tmp_path / "shards"
    root.mkdir()
    for i in range(2):
        shard = root / f"qwen-shadow-123-shard-00{i}-of-002.jsonl.gz"
        with gzip.open(shard, "wt", encoding="utf-8") as fh:
            fh.write(json.dumps({"candidate_id": "TED:dup", "title": "Website"}) + "\n")
    with pytest.raises(SystemExit):
        post_guard.discover_notice_context(root, {"TED:dup"})


def test_transient_transport_failure_is_retried_before_split(monkeypatch):
    calls = []

    def flaky(url, payload, timeout):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise urllib.error.URLError("temporary")
        return {"choices": [{"message": {"content": '{"x":[]}'}}]}

    monkeypatch.setattr(rich, "_original_post_json", flaky)
    monkeypatch.setattr(rich, "TRANSPORT_RETRIES", 1)
    monkeypatch.setattr(rich, "TRANSPORT_RETRY_BASE_SECONDS", 0.0)
    response = rich.retrying_post_json("http://localhost", {"x": 1}, 5)
    assert len(calls) == 2
    assert response["choices"][0]["message"]["content"] == '{"x":[]}'


def test_permanent_http_error_is_not_retried(monkeypatch):
    calls = []

    def bad_request(url, payload, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(url, 400, "bad", hdrs=None, fp=None)

    monkeypatch.setattr(rich, "_original_post_json", bad_request)
    monkeypatch.setattr(rich, "TRANSPORT_RETRIES", 3)
    monkeypatch.setattr(rich, "TRANSPORT_RETRY_BASE_SECONDS", 0.0)
    with pytest.raises(urllib.error.HTTPError):
        rich.retrying_post_json("http://localhost", {}, 5)
    assert len(calls) == 1
