from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from aggregate_dce import candidate_document_relevance


def test_generic_procurement_manual_is_not_candidate_specific_dce():
    candidate = {
        "candidate_id": "US-SAM:cf6d6b17fdb94495be47690e1042a87d",
        "title": "CCA, DIGITAL I/O",
        "solicitation_number": "N0010426QABCD",
    }
    generic_piee = (
        "PIEE Solicitation Module enhancements. This procurement manual explains digital workflows, "
        "contractor registration, award criteria, submissions, references, and system administration."
    )
    result = candidate_document_relevance(candidate, generic_piee)
    assert result["proven"] is False
    assert result["status"] == "UNPROVEN_CANDIDATE_DOCUMENT_MATCH"


def test_explicit_solicitation_reference_proves_candidate_match():
    candidate = {
        "title": "Opaque requirement title",
        "solicitation_number": "N0010426QABCD",
    }
    corpus = "Request for quotation N0010426QABCD. Scope of work and submission requirements follow."
    result = candidate_document_relevance(candidate, corpus)
    assert result["proven"] is True
    assert result["status"] == "PROVEN_BY_REFERENCE"


def test_exact_title_phrase_proves_candidate_match_without_reference():
    candidate = {"title": "Water Management Programming"}
    corpus = (
        "Statement of Work — Water Management Programming. The contractor shall develop and maintain "
        "the required software application and database interfaces."
    )
    result = candidate_document_relevance(candidate, corpus)
    assert result["proven"] is True
    assert result["status"] == "PROVEN_BY_TITLE_PHRASE"


def test_multiple_distinctive_title_tokens_can_prove_match():
    candidate = {"title": "Multilingual Video Captioning Services"}
    corpus = (
        "The supplier will provide multilingual captioning, subtitle preparation and accessibility "
        "services for the authority's audiovisual catalogue."
    )
    result = candidate_document_relevance(candidate, corpus)
    assert result["proven"] is True
    assert result["status"] == "PROVEN_BY_TITLE_TOKENS"
