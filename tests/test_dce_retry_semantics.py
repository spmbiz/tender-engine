import io
import json
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import fleet_controller as fc
import fleet_controller_v5 as v5


def deep_review_tar(rows):
    payload = "".join(json.dumps(r) + "\n" for r in rows).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("deep_review_queue.jsonl")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def install_semantic_asset(monkeypatch, run_id="123"):
    blob = deep_review_tar([
        {"candidate_id": "GOOD", "gate_readiness": True, "status": "DOWNLOADED_PUBLIC"},
        {"candidate_id": "MISS", "gate_readiness": False, "status": "AUTH_REQUIRED"},
    ])
    name = f"dce-deep-review-{run_id}.tar.gz"
    monkeypatch.setattr(v5.v4, "_release_assets", lambda rid: ({"id": 1}, [{"name": name}]))
    monkeypatch.setattr(v5.fc, "download_asset", lambda rel, asset_name: blob if asset_name == name else None)


def test_semantic_resolution_separates_gate_ready_from_retryable(monkeypatch):
    install_semantic_asset(monkeypatch)
    result = v5._semantic_resolution("123", ["GOOD", "MISS"])
    assert result is not None
    assert result["resolved_ids"] == ["GOOD"]
    assert result["retryable_ids"] == ["MISS"]
    assert result["retry_reasons"]["MISS"] == "AUTH_REQUIRED"


def test_retryable_attempt_is_only_temporarily_blocked(monkeypatch):
    install_semantic_asset(monkeypatch)
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(v5.fc, "NOW", now)
    monkeypatch.setattr(v5.v4, "_dispatch_postprocessing", lambda *args, **kwargs: None)

    state = {"processed_candidate_ids": [], "pending_dce_batch": {"candidate_ids": ["GOOD", "MISS"]}}
    pending = state["pending_dce_batch"]
    actions = []
    owns_lane = v5._semantic_commit_durable_batch(state, actions, pending, ["GOOD", "MISS"], "123", ["GOOD", "MISS"])

    assert owns_lane is False
    assert "GOOD" in state["processed_candidate_ids"]
    assert "MISS" in state["processed_candidate_ids"]
    assert "GOOD" not in state["dce_retry_after"]
    assert state["dce_retry_attempts"]["MISS"] == 1
    assert any(a["type"] == "dce_batch_semantically_committed" and a["resolved_gate_ready_processed"] == 1 for a in actions)

    monkeypatch.setattr(v5.fc, "NOW", now + timedelta(minutes=6))
    release_actions = []
    v5._expire_retry_cooldowns(state, release_actions)
    assert "GOOD" in state["processed_candidate_ids"]
    assert "MISS" not in state["processed_candidate_ids"]
    assert "MISS" not in state["dce_retry_after"]
    assert any(a["type"] == "dce_retry_cooldown_expired" for a in release_actions)


def test_missing_semantic_asset_never_permanently_processes_attempt(monkeypatch):
    monkeypatch.setattr(v5, "_semantic_resolution", lambda *args, **kwargs: None)
    state = {"processed_candidate_ids": [], "pending_dce_batch": {"candidate_ids": ["MISS"]}}
    pending = state["pending_dce_batch"]
    actions = []
    owns_lane = v5._semantic_commit_durable_batch(state, actions, pending, ["MISS"], "123", ["MISS"])
    assert owns_lane is True
    assert state["processed_candidate_ids"] == []
    assert state["pending_dce_batch"]["semantic_resolution_attempts"] == 1
