from datetime import datetime, timezone

from pipeline.discover_worldbank_procurement import pdt, row_to_record


def test_worldbank_date_parser_accepts_common_api_shapes():
    assert pdt("2026-08-16").date().isoformat() == "2026-08-16"
    assert pdt("08/16/2026").date().isoformat() == "2026-08-16"
    assert pdt("Aug 16, 2026").date().isoformat() == "2026-08-16"
    assert pdt("2026-08-16T12:30:00Z").tzinfo is not None


def test_worldbank_row_preserves_reference_and_type():
    row = {
        "id": "OP00499999",
        "notice_type": "Invitation for Bids",
        "notice_status": "Published",
        "noticedate": "2026-08-15",
        "submission_deadline_date": "2099-09-01",
        "project_ctry_name": "Belgium",
        "project_id": "P123456",
        "project_name": "Example Project",
        "bid_reference_no": "RFB-42",
        "bid_description": "Supply digital service",
        "procurement_group": "NC",
        "procurement_method_code": "RFB",
    }
    rec = row_to_record(row, datetime(2026, 8, 16, tzinfo=timezone.utc))
    assert rec is not None
    assert rec["notice_id"] == "OP00499999"
    assert rec["reference"] == "RFB-42"
    assert rec["notice_type"] == "Invitation for Bids"
    assert rec["notice_url"].endswith("OP00499999")
