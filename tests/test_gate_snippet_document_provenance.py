from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import extract_corpus
import extract_gates


def test_gate_snippet_maps_back_to_exact_extracted_document(tmp_path: Path):
    root = tmp_path / "candidate"
    files = root / "files"
    files.mkdir(parents=True)
    doc = files / "terms.txt"
    doc.write_text(
        "General procurement terms. Minimum annual turnover is EUR 100000. "
        "Tender submission deadline is 30 September 2099. "
        "Subcontracting is permitted with prior approval.",
        encoding="utf-8",
    )
    source_url = "https://procurement.example.test/tender/123/terms.txt"
    (root / "manifest.json").write_text(json.dumps({
        "candidate_id": "TEST:1",
        "status": "DOWNLOADED_PUBLIC",
        "files": [{"name": "terms.txt", "source_url": source_url}],
    }), encoding="utf-8")
    (root / "candidate.json").write_text(json.dumps({"candidate_id": "TEST:1"}), encoding="utf-8")
    (root / "evidence_quality.json").write_text(json.dumps({
        "gate_readiness": True,
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "derived_status": "DOWNLOADED_PUBLIC",
    }), encoding="utf-8")

    corpus_result = extract_corpus.process_candidate(root)
    assert corpus_result is not None
    index = json.loads((root / "document_index.json").read_text(encoding="utf-8"))
    assert len(index) == 1
    assert index[0]["corpus_start"] is not None
    assert index[0]["corpus_end"] > index[0]["corpus_start"]
    assert index[0]["source_url"] == source_url
    assert index[0]["sha256"]

    gate_result = extract_gates.process(root)
    assert gate_result is not None
    snippets = json.loads((root / "gate_snippets.json").read_text(encoding="utf-8"))
    item = snippets["categories"]["turnover_financial"][0]
    assert item["source"] == "files/terms.txt"
    assert item["source_url"] == source_url
    assert item["source_sha256"] == index[0]["sha256"]
    assert item["provenance_strength"] == "SOURCE_URL_ATTRIBUTED"
    assert item["raw_machine_format"] is False
    assert snippets["snippet_provenance"]["unattributed"] == 0


def test_raw_machine_format_is_explicitly_flagged_not_silently_promoted(tmp_path: Path):
    root = tmp_path / "candidate"
    files = root / "files"
    files.mkdir(parents=True)
    doc = files / "notice.xml"
    doc.write_text("<root><criterion>minimum turnover EUR 50000</criterion></root>", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "candidate_id": "TEST:XML",
        "status": "DOWNLOADED_PUBLIC",
        "files": [{"name": "notice.xml", "source_url": "https://example.test/notice.xml"}],
    }), encoding="utf-8")
    (root / "candidate.json").write_text(json.dumps({"candidate_id": "TEST:XML"}), encoding="utf-8")
    (root / "evidence_quality.json").write_text(json.dumps({
        "gate_readiness": True,
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "derived_status": "DOWNLOADED_PUBLIC",
    }), encoding="utf-8")

    extract_corpus.process_candidate(root)
    extract_gates.process(root)
    snippets = json.loads((root / "gate_snippets.json").read_text(encoding="utf-8"))
    item = snippets["categories"]["turnover_financial"][0]
    assert item["source"].endswith("notice.xml")
    assert item["raw_machine_format"] is True
    assert item["source_sha256"]
