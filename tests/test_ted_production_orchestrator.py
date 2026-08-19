from datetime import datetime, timezone

from pipeline.ted_production import build_delta_queries, build_year_queries


def test_delta_future_deadline_lane_has_no_publication_lookback():
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    queries = build_delta_queries(now, recent_days=3)
    future = queries["future-deadline"]
    assert "deadline >= 20260819" in future
    assert "deadline-receipt-request >= 20260819" in future
    assert "deadline-receipt-tender-date-lot >= 20260819" in future
    assert "PD =" not in future
    assert queries["recent-publication"] == "PD = (20260816 <> 20260819) AND form-type = competition"


def test_year_queries_are_deterministic_non_overlapping_calendar_shards():
    queries = build_year_queries(2016, 2026)
    assert list(queries) == list(range(2016, 2027))
    assert queries[2016] == "PD = (20160101 <> 20161231) AND form-type = competition"
    assert queries[2025] == "PD = (20250101 <> 20251231) AND form-type = competition"
    assert queries[2026] == "PD = (20260101 <> 20261231) AND form-type = competition"


def test_year_query_builder_refuses_inverted_range():
    try:
        build_year_queries(2027, 2026)
    except ValueError as exc:
        assert "current_year" in str(exc)
    else:
        raise AssertionError("expected ValueError")
