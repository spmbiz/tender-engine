from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.discover_gr_khmdhs_v2 as gr


def test_window_manifest_is_contiguous_and_never_wider_than_180(monkeypatch):
    class FakeNow:
        @staticmethod
        def date():
            return date(2026, 8, 20)

    monkeypatch.setattr(gr, "NOW", FakeNow())
    monkeypatch.setattr(gr, "HORIZON_YEAR", 2027)
    monkeypatch.setattr(gr, "WINDOW_DAYS", 180)
    windows = gr.window_manifest()
    assert windows[0][0] == date(2026, 8, 20)
    assert windows[-1][1] == date(2027, 12, 31)
    for i, (start, end) in enumerate(windows):
        assert (end - start).days + 1 <= 180
        if i:
            assert start == windows[i - 1][1] + gr.timedelta(days=1)


def test_normalize_requires_deadline_and_filters_cancelled(monkeypatch):
    monkeypatch.setattr(gr, "NOW", gr.datetime(2026, 8, 20, tzinfo=gr.timezone.utc))
    base = {
        "referenceNumber": "REF-1",
        "title": "Test contract",
        "finalSubmissionDate": "2026-09-10T12:00:00Z",
        "organization": {"value": "Buyer"},
    }
    row = gr.normalize(base)
    assert row is not None
    assert row["current"] is True
    assert row["deadline"].startswith("2026-09-10")

    cancelled = dict(base, cancelled=True)
    assert gr.normalize(cancelled)["current"] is False

    no_deadline = dict(base)
    no_deadline.pop("finalSubmissionDate")
    assert gr.normalize(no_deadline) is None


def test_cpv_supports_both_object_detail_shapes():
    a = {"objectDetails": [{"cpvs": [{"value": "12345678"}]}]}
    b = {"objectDetailsList": [{"cpvs": [{"name": "87654321"}]}]}
    assert gr.cpvs(a) == ["12345678"]
    assert gr.cpvs(b) == ["87654321"]
