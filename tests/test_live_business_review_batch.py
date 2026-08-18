import json
import subprocess
import sys
from pathlib import Path


def run_builder(tmp_path: Path, inbox: dict, bank: dict | None = None, ledger: dict | None = None) -> dict:
    inbox_p = tmp_path / "inbox.json"
    bank_p = tmp_path / "bank.json"
    ledger_p = tmp_path / "ledger.json"
    out_p = tmp_path / "out.json"
    inbox_p.write_text(json.dumps(inbox), encoding="utf-8")
    bank_p.write_text(json.dumps(bank or {"items": []}), encoding="utf-8")
    ledger_p.write_text(json.dumps(ledger or {"ticks": {}}), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            "pipeline/build_live_business_review_batch.py",
            "--inbox", str(inbox_p),
            "--final-bank", str(bank_p),
            "--ledger", str(ledger_p),
            "--out", str(out_p),
            "--max-items", "10",
        ],
        check=True,
    )
    return json.loads(out_p.read_text(encoding="utf-8"))


def base_row(cid: str, title: str, score: int = 60) -> dict:
    return {
        "candidate_id": cid,
        "title": title,
        "buyer": "Buyer",
        "deadline": "2026-09-20T12:00:00+00:00",
        "review_stage": "BUSINESS_GATES",
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "gate_readiness": True,
        "spm_post_dce_score": score,
        "evidence_by_gate": {},
    }


def test_native_digital_low_gate_burden_beats_vendor_hardware(tmp_path: Path):
    waters = base_row("TED:WATERS", "ICT services for Web Portal and Smart Phone Application", 69)
    waters["evidence_by_gate"] = {
        "turnover_financial": [{"text": "Criterion: Turnover during the last three financial years N/A"}],
        "subcontracting_consortium": [{"text": "A consortium or subcontracting arrangement may be used."}],
        "deliverables_scope": [{"text": "Maintain Go backend, web dashboard and Flutter mobile application."}],
    }
    citrix = base_row("TED:CITRIX", "Renewal Citrix NetScaler Web Application Firewall in SAP context", 72)
    citrix["evidence_by_gate"] = {
        "references_experience": [{"text": "At least three comparable references are required."}],
        "certifications_partner": [{"text": "Citrix product certification and vendor expertise required."}],
        "deliverables_scope": [{"text": "Citrix NetScaler hardware appliance and SAP firewall operations."}],
    }
    out = run_builder(tmp_path, {"review_queue": [citrix, waters]})
    assert [x["candidate_id"] for x in out["items"]][:2] == ["TED:WATERS", "TED:CITRIX"]
    assert "native_spm_scope" in out["items"][0]["rank_reasons"]
    assert "vendor_or_enterprise_specialist" in out["items"][1]["rank_reasons"]


def test_already_final_and_actually_reviewed_are_not_requeued(tmp_path: Path):
    a = base_row("A", "Website maintenance", 70)
    b = base_row("B", "Video production", 70)
    c = base_row("C", "Translation services", 70)
    bank = {"items": [{"candidate_id": "A", "classification": "GREEN"}]}
    ledger = {"ticks": {"b": {"candidate_id": "B", "reviewed": True}}}
    out = run_builder(tmp_path, {"review_queue": [a, b, c]}, bank=bank, ledger=ledger)
    assert [x["candidate_id"] for x in out["items"]] == ["C"]
    assert out["skipped"]["already_final"] == 1
    assert out["skipped"]["already_reviewed"] == 1


def test_non_gate_ready_evidence_never_enters_final_review_batch(tmp_path: Path):
    bad = base_row("BAD", "Website redesign", 90)
    bad["gate_readiness"] = False
    bad["content_quality"] = "UNKNOWN_RETRIEVED_DOCUMENT"
    out = run_builder(tmp_path, {"review_queue": [bad]})
    assert out["items"] == []
    assert out["skipped"]["not_gate_ready"] == 1


def test_builder_never_emits_final_verdict_fields(tmp_path: Path):
    row = base_row("A", "Website redesign", 90)
    out = run_builder(tmp_path, {"review_queue": [row]})
    item = out["items"][0]
    assert item["finality"] == "COMPACT_REVIEW_INPUT_NOT_A_VERDICT"
    assert "classification" not in item
    assert "verdict" not in item
