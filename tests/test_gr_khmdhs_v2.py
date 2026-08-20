from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.discover_gr_khmdhs_v2 as gr
import pipeline.discover_gr_khmdhs_v3 as grv3


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


class FakeResponse:
    def __init__(self, *, status=404, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_verified_no_data_404_is_strictly_bounded_to_page_zero_and_explicit_message():
    explicit = FakeResponse(payload={"error": "No data found for the given criteria"})
    assert gr.verified_no_data_404(explicit, 0) is True
    assert gr.verified_no_data_404(explicit, 1) is False

    generic = FakeResponse(payload={"error": "Not Found"}, text="Not Found")
    assert gr.verified_no_data_404(generic, 0) is False

    html = FakeResponse(payload=ValueError("not json"), text="No data found for the given criteria")
    assert gr.verified_no_data_404(html, 0) is True


def test_v3_accepts_only_the_observed_publisher_no_notices_message():
    observed = FakeResponse(payload={"message": "No notices found for the given criteria", "status": 404})
    assert grv3.verified_no_data_404(observed, 0) is True
    assert grv3.verified_no_data_404(observed, 1) is False

    wrong_status = FakeResponse(payload={"message": "No notices found for the given criteria", "status": 500})
    assert grv3.verified_no_data_404(wrong_status, 0) is False

    other_404 = FakeResponse(payload={"message": "Not Found", "status": 404})
    assert grv3.verified_no_data_404(other_404, 0) is False


def test_retry_after_parses_seconds(monkeypatch):
    monkeypatch.setattr(gr, "MAX_RETRY_AFTER", 90.0)
    response = FakeResponse(status=429, payload={}, headers={"Retry-After": "12"})
    assert gr.retry_after_seconds(response) == 12.0
