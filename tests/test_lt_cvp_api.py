from datetime import datetime, timezone

from pipeline.discover_lt_cvp_api import cpv_list, normalize_row, parse_source_dt


def test_malformed_migrated_date_is_rejected():
    assert parse_source_dt("14-06-0028 00:00:00") is None
    assert parse_source_dt("16-08-2026 12:30:00") is not None


def test_current_requires_valid_future_deadline():
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    base = {
        "id": 4181810,
        "title": "Digital services",
        "caName": "Buyer LT",
        "caNumber": "188656261",
        "datePublished": "15-08-2026 10:00:00",
        "procedure": "Open",
        "status": "Submission",
        "description": "Public procurement",
        "procurementType": "Services",
        "cpvCodes": "72413000, 72200000",
        "estimatedValue": "125000.00",
        "nutsCode": "LT",
        "aboveThreshold": True,
    }
    future = normalize_row({**base, "tenderSubmissionDeadline": "01-09-2026 12:00:00"}, now)
    assert future is not None
    assert future["current"] is True
    assert future["buyer_id"] == "188656261"
    assert future["cpv"] == ["72413000", "72200000"]
    assert future["estimated_value"] == 125000.0

    missing = normalize_row({**base, "tenderSubmissionDeadline": None}, now)
    assert missing is not None
    assert missing["current"] is False
    assert missing["currentness_evidence"] == "DEADLINE_NOT_FUTURE_OR_UNKNOWN"

    corrupted = normalize_row({**base, "tenderSubmissionDeadline": "14-06-0028 00:00:00"}, now)
    assert corrupted is not None
    assert corrupted["current"] is False
    assert corrupted["date_quality"]["deadline"] == "INVALID_SOURCE_VALUE"


def test_cpv_parser_is_deterministic():
    assert cpv_list("72413000; 72200000 79810000") == ["72413000", "72200000", "79810000"]
