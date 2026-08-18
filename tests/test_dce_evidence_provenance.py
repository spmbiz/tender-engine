from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from dce_evidence_quality import classify_candidate


def make_case(*, candidate_id: str, notice_id: str, source_url: str, corpus: str, portal: str = "GR_KHMDHS"):
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    candidate = {
        "candidate_id": candidate_id,
        "notice_id": notice_id,
        "portal": portal,
        "source": portal,
        "title": "ΔΟΚΙΜΑΣΤΙΚΗ ΔΙΑΚΗΡΥΞΗ",
    }
    manifest = {
        "candidate_id": candidate_id,
        "status": "DOWNLOADED_PUBLIC",
        "candidate": candidate,
        "files": [{
            "name": f"{notice_id}.pdf",
            "source_url": source_url,
            "content_type": "application/pdf",
        }],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
    (root / "document_index.json").write_text(json.dumps([{
        "name": f"{notice_id}.pdf",
        "kind": "pdf",
        "text_chars": len(corpus),
    }]), encoding="utf-8")
    (root / "corpus.txt").write_text(corpus, encoding="utf-8")
    return td, root


def test_exact_official_khmdhs_attachment_is_gate_ready_even_without_latin_markers():
    notice_id = "26PROC019637881"
    corpus = "ΕΛΛΗΝΙΚΟ ΚΕΙΜΕΝΟ ΔΗΜΟΣΙΑΣ ΣΥΜΒΑΣΗΣ " * 300
    td, root = make_case(
        candidate_id=f"GR-KHMDHS:{notice_id}",
        notice_id=notice_id,
        source_url=f"https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/{notice_id}",
        corpus=corpus,
    )
    try:
        x = classify_candidate(root)
        assert x["gate_readiness"] is True
        assert x["content_quality"] == "SUBSTANTIVE_DCE_PRESENT"
        assert x["derived_status"] == "DOWNLOADED_PUBLIC"
        assert x["official_khmdhs_provenance"]["matched"] is True
        assert "exact_official_khmdhs_notice_attachment_provenance_matches_candidate_id" in x["reasons"]
    finally:
        td.cleanup()


def test_wrong_khmdhs_notice_id_never_passes_provenance_guard():
    td, root = make_case(
        candidate_id="GR-KHMDHS:26PROC019637881",
        notice_id="26PROC019637881",
        source_url="https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/DIFFERENT",
        corpus="ΓΕΝΙΚΟ ΚΕΙΜΕΝΟ " * 300,
    )
    try:
        x = classify_candidate(root)
        assert x["official_khmdhs_provenance"]["matched"] is False
        assert x["gate_readiness"] is False
        assert x["content_quality"] == "UNKNOWN_RETRIEVED_DOCUMENT"
    finally:
        td.cleanup()


def test_lookalike_host_never_passes_provenance_guard():
    notice_id = "26PROC019637881"
    td, root = make_case(
        candidate_id=f"GR-KHMDHS:{notice_id}",
        notice_id=notice_id,
        source_url=f"https://evil-example.com/khmdhs-opendata/notice/attachment/{notice_id}",
        corpus="ΓΕΝΙΚΟ ΚΕΙΜΕΝΟ " * 300,
    )
    try:
        x = classify_candidate(root)
        assert x["official_khmdhs_provenance"]["matched"] is False
        assert x["gate_readiness"] is False
    finally:
        td.cleanup()


def test_official_endpoint_without_extractable_text_remains_blocked():
    notice_id = "26PROC019637881"
    td, root = make_case(
        candidate_id=f"GR-KHMDHS:{notice_id}",
        notice_id=notice_id,
        source_url=f"https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/{notice_id}",
        corpus="tiny",
    )
    try:
        x = classify_candidate(root)
        assert x["gate_readiness"] is False
        assert x["content_quality"] == "EXTRACTION_EMPTY"
    finally:
        td.cleanup()


def test_non_greek_same_path_shape_never_passes():
    notice_id = "26PROC019637881"
    td, root = make_case(
        candidate_id=f"TED:{notice_id}",
        notice_id=notice_id,
        source_url=f"https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/{notice_id}",
        corpus="GENERAL DOCUMENT TEXT " * 300,
        portal="TED",
    )
    try:
        x = classify_candidate(root)
        assert x["official_khmdhs_provenance"]["matched"] is False
    finally:
        td.cleanup()
