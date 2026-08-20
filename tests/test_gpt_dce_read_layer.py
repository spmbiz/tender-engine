from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE))

from build_gpt_dce_read_layer import build_candidate_layer


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_candidate_layer_creates_navigable_markdown_without_inventing_gate_pass(tmp_path):
    root = tmp_path / "TED-TEST-1"
    root.mkdir()
    corpus = (
        "Supplier must have annual turnover of EUR 100000. "
        "Subcontracting is permitted. Deadline 1 September 2026."
    )
    (root / "corpus.txt").write_text(corpus, encoding="utf-8")
    write_json(
        root / "candidate.json",
        {
            "candidate_id": "TED:TEST-1",
            "title": "Website maintenance services",
            "buyer": "Test Buyer",
            "deadline": "2026-09-01T12:00:00+02:00",
            "estimated_value": 80000,
            "currency": "EUR",
            "description": "Maintain a public website and mobile application.",
        },
    )
    write_json(root / "manifest.json", {"candidate_id": "TED:TEST-1", "portal": "TED", "status": "DOWNLOADED_PUBLIC"})
    write_json(
        root / "document_index.json",
        [
            {
                "path": "files/RC.pdf",
                "name": "RC.pdf",
                "sha256": "abc",
                "kind": "pdf",
                "corpus_start": 0,
                "corpus_end": len(corpus),
                "source_url": "https://example.test/rc.pdf",
            }
        ],
    )
    write_json(
        root / "gate_snippets.json",
        {
            "gate_readiness": True,
            "content_quality": "SUBSTANTIVE_DCE_PRESENT",
            "canonical_gate_names": ["turnover_financial", "insurance_bonds"],
            "categories": {
                "turnover_financial": [
                    {
                        "match": "turnover",
                        "source": "files/RC.pdf",
                        "source_url": "https://example.test/rc.pdf",
                        "source_sha256": "abc",
                        "snippet": "Supplier must have annual turnover of EUR 100000.",
                    }
                ],
                "insurance_bonds": [],
            },
        },
    )
    write_json(root / "evidence_quality.json", {"gate_readiness": True, "content_quality": "SUBSTANTIVE_DCE_PRESENT"})
    write_json(root / "authority_conflicts.json", {"deadline": {"status": "AUTHORITATIVE", "conflict": False}})

    result = build_candidate_layer(root)
    assert result["candidate_id"] == "TED:TEST-1"
    read_root = root / "gpt_read"
    assert (read_root / "README.md").is_file()
    assert (read_root / "BRIEF.md").is_file()
    assert (read_root / "DCE_INDEX.md").is_file()
    assert (read_root / "GATES.md").is_file()
    assert (read_root / "GATES.json").is_file()
    assert (read_root / "docs" / "001_RC.md").is_file()

    gates_md = (read_root / "GATES.md").read_text(encoding="utf-8")
    assert "[RC.pdf](docs/001_RC.md)" in gates_md
    assert "annual turnover of EUR 100000" in gates_md
    assert "No snippet extracted. Status remains UNKNOWN" in gates_md

    gates_json = json.loads((read_root / "GATES.json").read_text(encoding="utf-8"))
    assert gates_json["gates"]["turnover_financial"]["review_status"] == "UNKNOWN"
    assert gates_json["gates"]["insurance_bonds"]["review_status"] == "UNKNOWN"

    doc_md = (read_root / "docs" / "001_RC.md").read_text(encoding="utf-8")
    assert "https://example.test/rc.pdf" in doc_md
    assert "The downloaded original remains authoritative" in doc_md
