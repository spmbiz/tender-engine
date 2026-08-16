from __future__ import annotations

from pipeline.postprocess_gpt_review_backlog import harden_row


def _row(
    title: str,
    text: str,
    score: int = 70,
    status=None,
    proven=False,
    *,
    deadline_resolved: bool = True,
    deadline_status: str = "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE",
):
    return {
        "candidate_id": title,
        "title": title,
        "portal": "TEST",
        "deadline": "2026-09-01T10:00:00Z",
        "deadline_resolved": deadline_resolved,
        "deadline_authority_status": deadline_status,
        "spm_post_dce_score": score,
        "spm_fit_band": "HOT",
        "spm_friction_signals": [],
        "candidate_document_relevance": {"status": status, "proven": proven},
        "evidence_by_gate": {"deliverables_scope": [{"text": text}]},
    }


def test_legacy_exact_title_reproves_irish_ar_dce():
    row = _row(
        "Animation and Software Development",
        "CFT: Animation and Software Development. WebAR app deployment, QR linking and animated AR characters.",
        score=67,
    )
    out = harden_row(row)
    assert out is not None
    assert out["candidate_document_relevance"]["proven"] is True
    assert out["candidate_document_relevance"]["status"] == "PROVEN_BY_BACKFILL_TITLE_PHRASE"
    assert out["spm_fit_band"] == "HOT"


def test_explicit_unproven_modern_relevance_stays_excluded():
    row = _row("Website redesign", "website redesign", status="UNPROVEN_CANDIDATE_DOCUMENT_MATCH", proven=False)
    assert harden_row(row) is None


def test_sdvosb_transcription_drops_out_of_hot():
    row = _row(
        "Court Reporting and Transcription",
        "This acquisition is set-aside for Service-Disabled Veteran-Owned Small Business (SDVOSB) concerns.",
        score=67,
        status="PROVEN_BY_TITLE_TOKENS",
        proven=True,
    )
    out = harden_row(row)
    assert out is not None
    assert out["spm_fit_band"] == "LOW"
    assert "us-sdvosb-set-aside" in out["spm_friction_signals"]


def test_shall_be_us_citizens_variant_drops_out_of_hot():
    row = _row(
        "Social Media Management",
        "All Contractor personnel that have access to agency data in any form shall be US citizens.",
        score=72,
        status="PROVEN_BY_TITLE_PHRASE",
        proven=True,
    )
    out = harden_row(row)
    assert out is not None
    assert out["spm_fit_band"] == "LOW"
    assert "us-citizens-only" in out["spm_friction_signals"]


def test_deadline_conflict_cannot_remain_hot():
    row = _row(
        "Interactive web application",
        "Interactive web application and digital experience",
        score=78,
        status="PROVEN_BY_TITLE_TOKENS",
        proven=True,
        deadline_resolved=False,
        deadline_status="DEADLINE_CONFLICT_REVIEW_REQUIRED",
    )
    out = harden_row(row)
    assert out is not None
    assert out["spm_post_dce_score"] <= 39
    assert out["spm_fit_band"] == "MAYBE"
    assert "deadline-conflict" in out["spm_friction_signals"]


def test_unknown_deadline_can_stay_good_but_not_hot():
    row = _row(
        "Website redesign",
        "Website redesign and CMS migration",
        score=76,
        status="PROVEN_BY_TITLE_PHRASE",
        proven=True,
        deadline_resolved=False,
        deadline_status="UNKNOWN_NO_DCE_DEADLINE_PARSED",
    )
    out = harden_row(row)
    assert out is not None
    assert out["spm_post_dce_score"] <= 59
    assert out["spm_fit_band"] == "GOOD"
    assert "deadline-unresolved" in out["spm_friction_signals"]


def test_does_not_constitute_rfp_market_research_is_demoted():
    row = _row(
        "Datalab redesign and O&M",
        "This does not constitute a Request for Proposals (RFP), Request for Quotations, Invitation for Bids, or a commitment.",
        score=55,
        status="PROVEN_BY_TITLE_TOKENS",
        proven=True,
    )
    out = harden_row(row)
    assert out is not None
    assert out["spm_fit_band"] == "LOW"
    assert "market-research-not-solicitation" in out["spm_friction_signals"]


def test_direct_8a_award_is_demoted():
    row = _row(
        "IT support services",
        "This acquisition will be awarded as a direct 8(a) Alaskan Native Corporation award.",
        score=52,
        status="PROVEN_BY_TITLE_TOKENS",
        proven=True,
    )
    out = harden_row(row)
    assert out is not None
    assert out["spm_fit_band"] == "LOW"
    assert "us-8a-set-aside" in out["spm_friction_signals"] or "us-direct-8a-award" in out["spm_friction_signals"]
