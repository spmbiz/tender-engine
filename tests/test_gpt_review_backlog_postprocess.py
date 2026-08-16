from __future__ import annotations

from pipeline.postprocess_gpt_review_backlog import harden_row


def _row(title: str, text: str, score: int = 70, status=None, proven=False):
    return {
        "candidate_id": title,
        "title": title,
        "portal": "TEST",
        "deadline": "2026-09-01T10:00:00Z",
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
