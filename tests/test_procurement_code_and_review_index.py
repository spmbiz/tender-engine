from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from procurement_code_prior import code_priority
from review_procedure_identity import strong_procedure_aliases


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


def test_strong_alias_parser_uses_explicit_etenders_resource_only():
    aliases = strong_procedure_aliases({
        "notice_url": "https://ted.europa.eu/en/notice/-/detail/571373-2026",
        "evidence_quality_summary": {
            "source_urls": ["https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId=8853905"]
        },
    })
    assert "ie_resource:8853905" in aliases
    assert not strong_procedure_aliases({"title": "same words", "buyer": "same buyer"})


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


def _run_index(tmp_path: Path, release: Path, final_payload=None):
    existing = tmp_path / "existing.json"
    final = tmp_path / "final.json"
    ledger = tmp_path / "ledger.json"
    out = tmp_path / "index.json"
    existing.write_text('{"items":[]}\n', encoding="utf-8")
    final.write_text(json.dumps(final_payload or {"items": []}) + "\n", encoding="utf-8")
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
    return json.loads(out.read_text(encoding="utf-8"))


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
    payload = _run_index(tmp_path, release)
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
    payload = _run_index(tmp_path, tmp_path / "release", {"items": [{"candidate_id": "DONE:1"}]})
    assert [x["candidate_id"] for x in payload["items"]] == ["KEEP:1"]


def test_review_index_collapses_only_shared_strong_procedure_alias(tmp_path: Path):
    release = tmp_path / "release" / "32100000003"
    release.mkdir(parents=True)
    ted = _review_row("TED:571373-2026", "Immersive Learning Platform", 70)
    ie = _review_row("IE:8853905", "Immersive Learning Platform", 72)
    ted["evidence_quality"] = {
        "raw_status": "DOWNLOADED_PUBLIC",
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "gate_readiness": True,
        "text_chars": 50000,
        "documents_with_text": 4,
        "source_urls": ["https://www.etenders.gov.ie/epps/cft/listContractDocuments.do?resourceId=8853905"],
    }
    ie["notice_url"] = "https://www.etenders.gov.ie/epps/cft/prepareViewCfTWS.do?resourceId=8853905"
    ie["evidence_quality"] = dict(ted["evidence_quality"])
    unrelated = _review_row("OTHER:1", "Immersive Learning Platform", 60)
    (release / "fast-adjudication-shard-0.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in [ted, ie, unrelated]), encoding="utf-8"
    )
    payload = _run_index(tmp_path, tmp_path / "release")
    assert payload["count"] == 2
    assert payload["counts"]["cross_portal_duplicates_collapsed"] == 1
    joined = [x for x in payload["items"] if "ie_resource:8853905" in (x.get("procedure_aliases") or [])]
    assert len(joined) == 1
    assert any(x["candidate_id"] == "OTHER:1" for x in payload["items"])


def _write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")


def test_coded_scheduler_prioritizes_codes_but_preserves_candidate_pool(tmp_path: Path):
    state = tmp_path / "state.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    snapshot = tmp_path / "snapshot.jsonl"
    blocked = tmp_path / "blocked.json"
    review = tmp_path / "review.json"
    dispatch = tmp_path / "dispatch.json"
    attempts = tmp_path / "attempts.jsonl"

    ids = ["WEB:1", "GENERIC:1", "BUILD:1"]
    state_rows = []
    ledger_rows = []
    snapshot_rows = []
    for i, cid in enumerate(ids):
        h = f"hash-{i}"
        state_rows.append({
            "canonical_notice_id": cid,
            "material_fields_hash": h,
            "classification": "FIT",
            "survival_decision": "KEEP",
            "dce_eligible": True,
            "lean_attractiveness": "MEDIUM",
            "delivery_mode": "DIRECT_DIGITAL",
            "friction_flags": [],
        })
        ledger_rows.append({
            "canonical_notice_id": cid,
            "material_fields_hash": h,
            "ledger_event": "NEW",
            "first_seen_at": "2099-01-01T00:00:00+00:00",
        })
        cpv = "72413000" if cid.startswith("WEB") else "45000000" if cid.startswith("BUILD") else ""
        snapshot_rows.append({
            "candidate_id": cid,
            "title": "Website design" if cid.startswith("WEB") else "Construction work" if cid.startswith("BUILD") else "General service",
            "cpv_or_category": cpv,
            "deadline": "2099-09-18T12:00:00+00:00",
            "wide_read_run_id": "TEST",
        })
    _write_jsonl(state, state_rows)
    _write_jsonl(ledger, ledger_rows)
    _write_jsonl(snapshot, snapshot_rows)
    blocked.write_text('{"processed_candidate_ids":[],"dce_retry_after":{}}\n', encoding="utf-8")
    review.write_text('{"items":[]}\n', encoding="utf-8")
    dispatch.write_text('{"records":{}}\n', encoding="utf-8")
    attempts.write_text("", encoding="utf-8")

    def run(limit: int):
        out = tmp_path / f"out-{limit}.jsonl"
        summary = tmp_path / f"summary-{limit}.json"
        subprocess.run([
            sys.executable, str(ROOT / "pipeline/build_qwen_dce_selection_coded.py"),
            "--state", str(state), "--ledger", str(ledger), "--snapshot", str(snapshot),
            "--blocked-state", str(blocked), "--review-backlog", str(review),
            "--dispatch-state", str(dispatch), "--attempt-ledger", str(attempts),
            "--out", str(out), "--summary", str(summary), "--source-run", "TEST",
            "--limit", str(limit), "--explore-share", "0", "--reject-audit-share", "0",
        ], cwd=ROOT, check=True)
        return [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()], json.loads(summary.read_text(encoding="utf-8"))

    top2, summary2 = run(2)
    ids2 = [x["candidate_id"] for x in top2]
    assert "WEB:1" in ids2
    assert "BUILD:1" not in ids2
    assert summary2["base_candidate_pool"] == 3
    assert summary2["code_prior"]["noncore_code_contradictions_in_pool"] == 1
    assert sum(summary2["selection_decisions"].values()) == summary2["selected"] == 2

    all3, summary3 = run(3)
    assert {x["candidate_id"] for x in all3} == set(ids)
    assert sum(summary3["selection_decisions"].values()) == summary3["selected"] == 3
    build = next(x for x in all3 if x["candidate_id"] == "BUILD:1")
    assert build["qwen"]["classification"] == "FIT"
    assert build["procurement_code_prior"]["contradiction"] is True
