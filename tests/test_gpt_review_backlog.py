from __future__ import annotations

from pipeline.build_gpt_review_backlog import compact_row, portfolio_select


def _row(cid: str, portal: str, title: str, text: str = "", coverage: int = 10):
    gates = {f"gate_{i}": [{"text": text or f"evidence {i}"}] for i in range(coverage)}
    return {
        "candidate_id": cid,
        "title": title,
        "buyer": "Buyer",
        "portal": portal,
        "deadline": "2026-09-01T12:00:00Z",
        "gate_readiness": True,
        "candidate_document_relevance": {"proven": True, "status": "PROVEN_BY_REFERENCE"},
        "gate_snippets": gates,
        "authority_conflicts": {"deadline": {"status": "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE", "conflict": False}},
        "preliminary_score": 80,
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
    }


def test_compact_row_keeps_authoritative_evidence_and_source_run():
    row = compact_row(_row("TED:1", "TED", "Website redesign and CMS migration"), "123")
    assert row is not None
    assert row["source_dce_run_id"] == 123
    assert row["candidate_document_relevance"]["proven"] is True
    assert row["spm_fit_band"] in {"HOT", "GOOD"}
    assert row["evidence_gate_coverage"] == 10


def test_unproven_document_never_enters_backlog():
    raw = _row("US:bad", "US_SAM", "Website redesign")
    raw["candidate_document_relevance"] = {"proven": False, "status": "UNPROVEN_CANDIDATE_DOCUMENT_MATCH"}
    assert compact_row(raw, "123") is None


def test_portfolio_prevents_single_portal_from_owning_priority_when_alternatives_exist():
    rows = []
    for i in range(20):
        rows.append(compact_row(_row(f"US:{i}", "US_SAM", f"Software services {i}"), "100"))
    for i in range(8):
        rows.append(compact_row(_row(f"TED:{i}", "TED", f"Website redesign {i}"), "101"))
    for i in range(6):
        rows.append(compact_row(_row(f"FR:{i}", "FR_BOAMP", f"Graphic design {i}"), "102"))
    selected = portfolio_select([r for r in rows if r], 20, 0.40)
    assert len(selected) == 20
    priority = [r for r in selected if r["review_lane"] == "SPM_PRIORITY"]
    us_priority = [r for r in priority if r["portal"] == "US_SAM"]
    assert len(us_priority) <= 8
    assert any(r["portal"] == "TED" for r in selected)
    assert any(r["portal"] == "FR_BOAMP" for r in selected)


def test_digital_training_survives_cumulative_backlog():
    row = compact_row(_row("IE:1", "IE_ETENDERS", "Digital training and e-learning content"), "200")
    assert row is not None
    assert row["spm_post_dce_score"] >= 40
