import json
from pathlib import Path

import pipeline.discover_ted as ted


class FakeResponse:
    def __init__(self, body: bytes, status=200, headers=None):
        self.content = body
        self.status_code = status
        self.headers = headers or {}
        self.text = body.decode("utf-8", errors="replace")
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


def configure(monkeypatch, tmp_path: Path, fake_session: FakeSession):
    monkeypatch.setattr(ted, "OUT", tmp_path)
    monkeypatch.setattr(ted, "REQUEST_RETRIES", 3)
    monkeypatch.setattr(ted, "BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(ted, "PAGE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(ted, "HARD_MAX_PAGES", 0)
    monkeypatch.setattr(ted.time, "sleep", lambda _: None)
    monkeypatch.setattr(ted.requests, "Session", lambda: fake_session)


def test_malformed_http_200_retries_same_iteration_position(monkeypatch, tmp_path):
    broken = FakeResponse(b'{"notices":[{"publication-number":"123-2026"')
    good_payload = {
        "totalNoticeCount": 1,
        "notices": [
            {
                "publication-number": "123-2026",
                "publication-date": "2026-08-19+02:00",
                "deadline-receipt-request": ["2099-09-01T12:00:00+02:00"],
            }
        ],
    }
    good = FakeResponse(json.dumps(good_payload).encode())
    fake = FakeSession([broken, good])
    configure(monkeypatch, tmp_path, fake)

    stats = ted.run()

    assert len(fake.calls) == 2
    assert fake.calls[0]["json"] == fake.calls[1]["json"]
    assert stats["enumeration_complete"] is True
    assert stats["current_materialized"] == 1
    assert stats["malformed_json_retry_events"] == 1
    assert any(e.get("type") == "MALFORMED_JSON_200" for e in stats["retry_events"])


def test_active_scope_does_not_override_past_deadline(monkeypatch, tmp_path):
    payload = {
        "totalNoticeCount": 1,
        "notices": [
            {
                "publication-number": "8543-2026",
                "publication-date": "2026-01-08+01:00",
                "deadline-receipt-request": ["2026-01-20T12:00:00+01:00"],
            }
        ],
    }
    fake = FakeSession([FakeResponse(json.dumps(payload).encode())])
    configure(monkeypatch, tmp_path, fake)

    stats = ted.run()

    assert stats["enumeration_complete"] is True
    assert stats["materialized_unique"] == 1
    assert stats["current_materialized"] == 0
    row = json.loads((tmp_path / "active.jsonl").read_text().strip())
    assert row["current"] is False
    assert row["currentness_evidence"] == "PARSED_PAST_DEADLINE"
    assert (tmp_path / "current.jsonl").read_text() == ""
