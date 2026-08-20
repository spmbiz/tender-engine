from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.discover_mt_epps_ocds as mt


def test_month_parser_and_selection(monkeypatch):
    assert mt.month_tuple_from_url("https://x/ocds/services/recordpackage/getrecordpackage/2019/10") == (2019, 10)
    assert mt.month_tuple_from_url("https://x/ocds/services/recordpackage/getrecordpackage/2026/8") == (2026, 8)
    assert mt.month_tuple_from_url("https://x/not-a-package") is None

    manifest = [
        {"month": "2019-09", "month_tuple": (2019, 9)},
        {"month": "2019-10", "month_tuple": (2019, 10)},
        {"month": "2026-07", "month_tuple": (2026, 7)},
        {"month": "2026-08", "month_tuple": (2026, 8)},
    ]
    monkeypatch.setattr(mt, "MODE", "reconcile")
    assert [x["month"] for x in mt.select_manifest(manifest)] == ["2019-10", "2026-07", "2026-08"]


def test_iter_records_accepts_package_and_direct_record():
    a = {"ocid": "ocds-a", "compiledRelease": {"ocid": "ocds-a", "tender": {"title": "A"}}}
    b = {"ocid": "ocds-b", "compiledRelease": {"ocid": "ocds-b", "tender": {"title": "B"}}}
    assert list(mt.iter_records({"records": [a, b]})) == [a, b]
    assert list(mt.iter_records(a)) == [a]
    assert list(mt.iter_records([{"records": [a]}, b])) == [a, b]


def test_normalize_promotes_only_future_deadline_and_keeps_unknown_radar(monkeypatch):
    monkeypatch.setattr(mt, "NOW", datetime(2026, 8, 20, tzinfo=timezone.utc))

    live_record = {
        "ocid": "ocds-mt-live",
        "date": "2026-08-19T10:00:00Z",
        "compiledRelease": {
            "ocid": "ocds-mt-live",
            "id": "release-live",
            "date": "2026-08-19T10:00:00Z",
            "tender": {
                "title": "Live Malta tender",
                "status": "active",
                "tenderPeriod": {"endDate": "2026-09-10T12:00:00Z"},
            },
        },
    }
    candidate, radar = mt.normalize_record(live_record, "2026-08")
    assert candidate is not None and candidate["current"] is True
    assert radar is None

    unknown_record = {
        "ocid": "ocds-mt-unknown",
        "date": "2026-08-19T10:00:00Z",
        "compiledRelease": {
            "ocid": "ocds-mt-unknown",
            "id": "release-unknown",
            "date": "2026-08-19T10:00:00Z",
            "tender": {"title": "Unknown deadline", "status": "active"},
        },
    }
    candidate, radar = mt.normalize_record(unknown_record, "2026-08")
    assert candidate is not None and candidate["current"] is False
    assert radar is not None and radar["current"] is False
    assert radar["currentness_evidence"] == "MALTA_EPPS_OCDS_ACTIVE_OR_PLANNED_WITHOUT_DEADLINE_RADAR_ONLY"


def test_terminal_status_is_not_current(monkeypatch):
    monkeypatch.setattr(mt, "NOW", datetime(2026, 8, 20, tzinfo=timezone.utc))
    record = {
        "ocid": "ocds-mt-done",
        "compiledRelease": {
            "ocid": "ocds-mt-done",
            "id": "release-done",
            "tender": {
                "title": "Completed tender",
                "status": "complete",
                "tenderPeriod": {"endDate": "2026-09-10T12:00:00Z"},
            },
        },
    }
    candidate, _ = mt.normalize_record(record, "2026-08")
    assert candidate is not None and candidate["current"] is False
