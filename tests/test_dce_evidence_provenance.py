from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from dce_evidence_quality import classify_candidate


def make_case(*, candidate_id: str, notice_id: str, source_url: str, corpus: str, portal: str = "GR_KHMDHS", extra_candidate: dict | None = None, extra_manifest: dict | None = None):
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    candidate = {
        "candidate_id": candidate_id,
        "notice_id": notice_id,
        "portal": portal,
        "source": portal,
        "title": "ΔΟΚΙΜΑΣΤΙΚΗ ΔΙΑΚΗΡΥΞΗ",
    }
    if extra_candidate:
        candidate.update(extra_candidate)
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
    if extra_manifest:
        manifest.update(extra_manifest)
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


def test_exact_official_placsp_atom_document_is_gate_ready():
    source_url = "https://contrataciondelsectorpublico.gob.es/wps/wcm/connect/official/GetDocumentsById?id=ABC"
    td, root = make_case(
        candidate_id="ES-PLACSP:official-entry-123",
        notice_id="official-entry-123",
        source_url=source_url,
        corpus="DOCUMENTO ESPECIFICO DEL EXPEDIENTE " * 250,
        portal="ES_PLACSP",
        extra_manifest={
            "placsp_atom_resolution": {
                "document_urls": [source_url],
                "match_method": "contract_folder_id",
                "contract_folder_id": "123/2026",
            },
            "dce_method_attempts": [{
                "method": "ES_PLACSP_OFFICIAL_ATOM_V17",
                "outcome": "ENTRY_FOUND",
            }],
        },
    )
    try:
        x = classify_candidate(root)
        assert x["official_placsp_provenance"]["matched"] is True
        assert x["gate_readiness"] is True
        assert "exact_official_placsp_matched_entry_document_provenance" in x["reasons"]
    finally:
        td.cleanup()


def test_placsp_unlisted_download_never_passes_official_provenance():
    downloaded = "https://contrataciondelsectorpublico.gob.es/wps/wcm/connect/other.pdf"
    official = "https://contrataciondelsectorpublico.gob.es/wps/wcm/connect/official/GetDocumentsById?id=ABC"
    td, root = make_case(
        candidate_id="ES-PLACSP:official-entry-123",
        notice_id="official-entry-123",
        source_url=downloaded,
        corpus="GENERIC DOCUMENT TEXT " * 250,
        portal="ES_PLACSP",
        extra_manifest={
            "placsp_atom_resolution": {"document_urls": [official], "match_method": "contract_folder_id"},
            "dce_method_attempts": [{"method": "ES_PLACSP_OFFICIAL_ATOM_V17", "outcome": "ENTRY_FOUND"}],
        },
    )
    try:
        x = classify_candidate(root)
        assert x["official_placsp_provenance"]["matched"] is False
        assert x["gate_readiness"] is False
    finally:
        td.cleanup()


def test_exact_za_ocds_typed_tender_document_is_gate_ready():
    ocid = "ocds-9t57fa-165832"
    source_url = "https://www.etenders.gov.za/home/Download/?blobName=rfb3264.pdf"
    td, root = make_case(
        candidate_id=f"ZA_ETENDERS_OCDS:{ocid}-2026-08-17",
        notice_id=f"{ocid}-2026-08-17",
        source_url=source_url,
        corpus="SOUTH AFRICAN PROCUREMENT DOCUMENT " * 250,
        portal="ZA_ETENDERS",
        extra_candidate={"ocid": ocid, "procedure_id": ocid},
        extra_manifest={
            "dce_method_attempts": [
                {
                    "method": "ZA_OCDS_RELEASE_API_V16",
                    "outcome": "RELEASE_FOUND",
                    "resolved_url": f"https://ocds-api.etenders.gov.za/api/OCDSReleases/release/{ocid}",
                },
                {
                    "method": "ZA_OCDS_DOCUMENT_V16",
                    "outcome": "DOWNLOADED",
                    "url": source_url,
                    "document_type": "biddingDocuments",
                    "title": "Bid document",
                },
            ]
        },
    )
    try:
        x = classify_candidate(root)
        assert x["official_za_ocds_provenance"]["matched"] is True
        assert x["gate_readiness"] is True
        assert "exact_official_za_ocds_typed_tender_document_provenance" in x["reasons"]
    finally:
        td.cleanup()


def test_za_ocds_tender_notice_type_does_not_unlock_gates():
    ocid = "ocds-9t57fa-165832"
    source_url = "https://www.etenders.gov.za/home/Download/?blobName=notice.pdf"
    td, root = make_case(
        candidate_id=f"ZA_ETENDERS_OCDS:{ocid}-2026-08-17",
        notice_id=f"{ocid}-2026-08-17",
        source_url=source_url,
        corpus="GENERIC PUBLICATION NOTICE TEXT " * 250,
        portal="ZA_ETENDERS",
        extra_candidate={"ocid": ocid},
        extra_manifest={
            "dce_method_attempts": [
                {
                    "method": "ZA_OCDS_RELEASE_API_V16",
                    "outcome": "RELEASE_FOUND",
                    "resolved_url": f"https://ocds-api.etenders.gov.za/api/OCDSReleases/release/{ocid}",
                },
                {
                    "method": "ZA_OCDS_DOCUMENT_V16",
                    "outcome": "DOWNLOADED",
                    "url": source_url,
                    "document_type": "tenderNotice",
                },
            ]
        },
    )
    try:
        x = classify_candidate(root)
        assert x["official_za_ocds_provenance"]["matched"] is False
        assert x["gate_readiness"] is False
    finally:
        td.cleanup()


def test_za_ocds_wrong_release_ocid_does_not_unlock_gates():
    ocid = "ocds-9t57fa-165832"
    source_url = "https://www.etenders.gov.za/home/Download/?blobName=rfb3264.pdf"
    td, root = make_case(
        candidate_id=f"ZA_ETENDERS_OCDS:{ocid}-2026-08-17",
        notice_id=f"{ocid}-2026-08-17",
        source_url=source_url,
        corpus="GENERIC DOCUMENT TEXT " * 250,
        portal="ZA_ETENDERS",
        extra_candidate={"ocid": ocid},
        extra_manifest={
            "dce_method_attempts": [
                {
                    "method": "ZA_OCDS_RELEASE_API_V16",
                    "outcome": "RELEASE_FOUND",
                    "resolved_url": "https://ocds-api.etenders.gov.za/api/OCDSReleases/release/ocds-9t57fa-DIFFERENT",
                },
                {
                    "method": "ZA_OCDS_DOCUMENT_V16",
                    "outcome": "DOWNLOADED",
                    "url": source_url,
                    "document_type": "biddingDocuments",
                },
            ]
        },
    )
    try:
        x = classify_candidate(root)
        assert x["official_za_ocds_provenance"]["matched"] is False
        assert x["gate_readiness"] is False
    finally:
        td.cleanup()
