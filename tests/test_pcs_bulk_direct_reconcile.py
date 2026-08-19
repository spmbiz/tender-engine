import json
from pathlib import Path

from pipeline.reconcile_uk_pcs_bulk_direct import reconcile


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")


def bulk_stats():
    return {
        "source": "UK_PCS_OCDS",
        "listing_contract": "PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_V3_PORTAL_MANIFEST_PLUS_101",
        "publication_window_enumeration_complete": True,
        "requests_expected": 10,
        "requests_completed": 10,
        "notice_types": [2, 101],
        "errors": [],
        "warnings": [],
        "enumeration_exhausted": False,
        "enumeration_complete": False,
        "live_coverage_credit_allowed": False,
    }


def direct_stats(total=1):
    return {
        "source": "UK_PCS_OCDS",
        "listing_contract": "PCS_CURRENT_OPPORTUNITIES_DIRECT_ASPNET_POST_V13_STATE_CHAIN",
        "total_reported": total,
        "source_rows_seen": total,
        "filtered_current_search_proven": True,
        "direct_filtered_post_proven": True,
        "count_matches_official_total": True,
        "enumeration_exhausted": True,
        "enumeration_complete": True,
        "errors": [],
    }


def setup_dirs(tmp_path, bulk_rows, direct_rows, *, direct_total=None):
    bulk = tmp_path / "bulk"
    direct = tmp_path / "direct"
    bulk.mkdir(); direct.mkdir()
    (bulk / "stats.json").write_text(json.dumps(bulk_stats()), encoding="utf-8")
    (direct / "stats.json").write_text(json.dumps(direct_stats(direct_total if direct_total is not None else len(direct_rows))), encoding="utf-8")
    write_jsonl(bulk / "current.jsonl", bulk_rows)
    write_jsonl(bulk / "raw.jsonl", bulk_rows)
    write_jsonl(direct / "current.jsonl", direct_rows)
    return bulk, direct


def test_exact_ocid_reconciliation_grants_credit(tmp_path):
    bulk_rows = [{"candidate_id": "UK_PCS_OCDS:release-1", "ocid": "ocds-abc", "route": {"ocid": "ocds-abc"}, "current": True}]
    direct_rows = [{"candidate_id": "UK-PCS:ocds-abc", "ocid": "ocds-abc", "reference": "AUG1", "current": True}]
    bulk, direct = setup_dirs(tmp_path, bulk_rows, direct_rows)
    proof = reconcile(bulk, direct)
    assert proof["coverage_complete"] is True
    assert proof["direct_missing_from_bulk"] == 0
    stats = json.loads((bulk / "stats.json").read_text())
    assert stats["enumeration_complete"] is True
    assert stats["live_coverage_credit_allowed"] is True


def test_missing_direct_row_is_preserved_but_credit_stays_closed(tmp_path):
    bulk_rows = [{"candidate_id": "UK_PCS_OCDS:release-1", "ocid": "ocds-abc", "current": True}]
    direct_rows = [
        {"candidate_id": "UK-PCS:ocds-abc", "ocid": "ocds-abc", "reference": "AUG1", "current": True},
        {"candidate_id": "UK-PCS:ocds-missing", "ocid": "ocds-missing", "reference": "AUG2", "title": "Missing", "current": True},
    ]
    bulk, direct = setup_dirs(tmp_path, bulk_rows, direct_rows)
    proof = reconcile(bulk, direct)
    assert proof["coverage_complete"] is False
    assert proof["direct_missing_from_bulk"] == 1
    final_rows = [json.loads(x) for x in (bulk / "current.jsonl").read_text().splitlines() if x.strip()]
    assert any(x.get("candidate_id") == "UK-PCS:ocds-missing" for x in final_rows)
    stats = json.loads((bulk / "stats.json").read_text())
    assert stats["enumeration_complete"] is False
    assert stats["live_coverage_credit_allowed"] is False


def test_titles_never_fuzzy_match_without_authoritative_identity(tmp_path):
    bulk_rows = [{"candidate_id": "UK_PCS_OCDS:release-1", "ocid": "ocds-one", "title": "Same title", "buyer": "Same buyer", "current": True}]
    direct_rows = [{"candidate_id": "UK-PCS:other", "ocid": "ocds-two", "reference": "OTHER", "title": "Same title", "buyer": "Same buyer", "current": True}]
    bulk, direct = setup_dirs(tmp_path, bulk_rows, direct_rows)
    proof = reconcile(bulk, direct)
    assert proof["coverage_complete"] is False
    assert proof["direct_missing_from_bulk"] == 1
