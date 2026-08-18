import json
import subprocess
import sys
from pathlib import Path


def run_tick(tmp_path: Path, adjudication: dict, pass_id: str = "test-pass") -> dict:
    reviews = tmp_path / "review.json"
    ledger = tmp_path / "ledger.json"
    reviews.write_text(json.dumps(adjudication), encoding="utf-8")
    if not ledger.exists():
        ledger.write_text(json.dumps({"schema": "GPT_WEB_REVIEW_LEDGER_V1", "ticks": {}, "passes": []}), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            "pipeline/gpt_web_tick.py",
            "--reviews", str(reviews),
            "--ledger", str(ledger),
            "--pass-id", pass_id,
        ],
        check=True,
    )
    return json.loads(ledger.read_text(encoding="utf-8"))


def test_persisted_adjudication_results_create_real_tick(tmp_path: Path):
    adjud = {
        "contract": "GPT_DCE_ADJUDICATION_V1",
        "source_dce_run": "32123828524",
        "created_at": "2026-08-18T13:52:00Z",
        "persist_to_final_bank": True,
        "results": [
            {
                "candidate_id": "TED:570846-2026",
                "classification": "GREEN",
                "review_key": "abc123",
            }
        ],
    }
    ledger = run_tick(tmp_path, adjud)
    tick = ledger["ticks"]["ted:570846-2026"]
    assert tick["reviewed"] is True
    assert tick["verdict"] == "GREEN"
    assert tick["source_dce_run_id"] == 32123828524
    assert tick["review_key"] == "abc123"
    assert len(ledger["ticks"]) == 1


def test_same_pass_is_idempotent_and_does_not_fake_extra_progress(tmp_path: Path):
    adjud = {
        "contract": "GPT_DCE_ADJUDICATION_V1",
        "source_dce_run": "32123828524",
        "persist_to_final_bank": True,
        "results": [{"candidate_id": "A", "classification": "RED"}],
    }
    first = run_tick(tmp_path, adjud, "persisted:a")
    second = run_tick(tmp_path, adjud, "persisted:a")
    assert len(second["ticks"]) == 1
    passes = [p for p in second["passes"] if p.get("review_pass_id") == "persisted:a"]
    assert len(passes) == 1
    assert passes[0]["reviewed_count"] == 1
    assert first["ticks"]["a"]["candidate_id"] == second["ticks"]["a"]["candidate_id"]
