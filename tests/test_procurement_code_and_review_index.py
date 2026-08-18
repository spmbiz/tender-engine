from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from procurement_code_prior import code_priority


def test_cpv_web_is_positive_priority_only():
    out = code_priority({"cpv_or_category": "72413000"})
    assert out["delta"] > 0
    assert out["positive"]
    assert not out["contradiction"]
    assert out["rule"] == "priority_only_never_drop_never_eligibility"


def test_cpv_construction_is_bounded_demotion_not_drop():
    out = code_priority({"cpv_or_category": "45000000"})
    assert out["delta"] == -20
    assert out["contradiction"] is True
    assert out["positive"] == []


def test_positive_digital_code_wins_in_mixed_procurement():
    out = code_priority({"cpv_codes": ["45000000", "72413000"]})
    assert out["delta"] > 0
    assert out["contradiction"] is False


def _review_row(cid: str, title: str, score: int = 80):
    return {
        "candidate_id": cid,
        "title": title,
        "buyer": "Test Buyer",
        "deadline": "2099-09-18T12:00:00+00:00",
        "classification": "MODEL_REVIEW_REQUIRED",
        "final_score": score,
        "preliminary_score": score,
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "gate_readiness": True,
        "gate_evidence_candidates": {
            "deliverables_scope": [{"text": title}],
            "submission": [{"text": "Tender deadline 18 September 2099"}],
        },
        "authority_conflicts": {
            "deadline": {
                "status": "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE",
                "conflict": False,
            }
        },
    }


def test_review_index_is_uncapped_and_quality_first(tmp_path: Path):
    release = tmp_path / "release"
    old = release / "32100000001"
    new = release / "32200000001"
    old.mkdir(parents=True)
    new.mkdir(parents=True)

    old_rows = [_review_row("OLD:BEST", "Website redesign and development", 88)]
    new_rows = [_review_row(f"NEW:{i:03d}", "Generic procurement support", 40) for i in range(199)]
    (old / "fast-adjudication-shard-0.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in old_rows), encoding="utf-8"
    )
    (new / "fast-adjudication-shard-0.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in new_rows), encoding="utf-8"
    )

    existing = tmp_path / "existing.json"
    final = tmp_path / "final.json"
    ledger = tmp_path / "ledger.json"
    out = tmp_path / "index.json"
    existing.write_text('{"items":[]}\n', encoding="utf-8")
    final.write_text('{"items":[]}\n', encoding="utf-8")
    ledger.write_text('{"ticks":{}}\n', encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "pipeline/build_gpt_review_index.py"),
            "--release-root", str(release),
            "--existing", str(existing),
            "--final-bank", str(final),
            "--review-ledger", str(ledger),
            "--out", str(out),
        ],
        cwd=ROOT,
        check=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 200
    assert payload["counts"]["overflow_beyond_hot_160"] == 40
    assert payload["items"][0]["candidate_id"] == "OLD:BEST"


def test_review_index_removes_final_bank_items(tmp_path: Path):
    release = tmp_path / "release" / "32100000002"
    release.mkdir(parents=True)
    rows = [_review_row("KEEP:1", "Website development"), _review_row("DONE:1", "Website development")]
    (release / "fast-adjudication-shard-0.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8"
    )
    existing = tmp_path / "existing.json"
    final = tmp_path / "final.json"
    ledger = tmp_path / "ledger.json"
    out = tmp_path / "index.json"
    existing.write_text('{"items":[]}\n', encoding="utf-8")
    final.write_text(json.dumps({"items": [{"candidate_id": "DONE:1"}]}) + "\n", encoding="utf-8")
    ledger.write_text('{"ticks":{}}\n', encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "pipeline/build_gpt_review_index.py"),
            "--release-root", str(tmp_path / "release"),
            "--existing", str(existing),
            "--final-bank", str(final),
            "--review-ledger", str(ledger),
            "--out", str(out),
        ],
        cwd=ROOT,
        check=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [x["candidate_id"] for x in payload["items"]] == ["KEEP:1"]
