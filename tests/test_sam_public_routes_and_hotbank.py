from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import discover_us_sam_bulk as samdisc
import publish_supergreen_hot as hot


def test_sam_workspace_link_is_canonicalized_to_public_supplier_page():
    nid = "7686bd844b36486a882c70d5a5436545"
    workspace = f"https://sam.gov/workspace/contract/opp/{nid}/view"
    assert samdisc._public_notice_url(nid, workspace) == f"https://sam.gov/opp/{nid}/view"
    assert samdisc._public_notice_url(None, workspace) == f"https://sam.gov/opp/{nid}/view"


def test_sam_resource_links_keep_opaque_attachment_urls():
    row = {
        "NoticeId": "abc",
        "Link": "https://sam.gov/workspace/contract/opp/abc/view",
        "ResourceLinks": '["https://api.sam.gov/prod/opportunities/v1/resources/files/opaque123/download", "https://files.example.gov/pws.pdf"]',
        "Description": "See attachment #2",
    }
    docs = samdisc._document_urls(row)
    assert "https://api.sam.gov/prod/opportunities/v1/resources/files/opaque123/download" in docs
    assert "https://files.example.gov/pws.pdf" in docs


def review_item(cid, run_id, score=80):
    return {
        "candidate_id": cid,
        "deadline": "2099-01-01T00:00:00+00:00",
        "deadline_resolved": True,
        "priority_score": score,
        "evidence_gate_coverage": 5,
        "source_dce_run_id": run_id,
        "hot_ready_at": "2099-01-01T00:00:00+00:00",
    }


def test_newer_dce_generation_resets_review_bank():
    existing = {
        "schema": "GPT_REVIEW_HOT_V1",
        "latest_dce_run_id": 100,
        "items": [review_item("OLD", 100, 89)],
    }
    incoming = [review_item("NEW", 101, 70)]
    merged = hot.merge_review(existing, incoming, set(), "101", "0", 30)
    assert merged["schema"] == "GPT_REVIEW_HOT_V2"
    assert merged["generation_reset"] is True
    assert [x["candidate_id"] for x in merged["items"]] == ["NEW"]


def test_late_old_shard_cannot_contaminate_newer_review_bank():
    existing = {
        "schema": "GPT_REVIEW_HOT_V2",
        "latest_dce_run_id": 101,
        "items": [review_item("NEW", 101, 70)],
    }
    late_old = [review_item("OLD-LATE", 100, 99)]
    merged = hot.merge_review(existing, late_old, set(), "100", "99", 30)
    assert merged == existing
