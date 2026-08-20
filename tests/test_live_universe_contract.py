from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_no_fuzzy_fallback_dedupe():
    merge = load("merge_discovery_test", "pipeline/merge_discovery.py")
    a = {"source": "X", "title": "Same", "buyer": "Buyer", "deadline": "2026-09-01", "description": "lot A"}
    b = {"source": "X", "title": "Same", "buyer": "Buyer", "deadline": "2026-09-01", "description": "lot B"}
    assert merge.canonical_key(a) != merge.canonical_key(b)
    assert merge.canonical_key(a) == merge.canonical_key(dict(a))


def test_authoritative_id_still_dedupes():
    merge = load("merge_discovery_id_test", "pipeline/merge_discovery.py")
    assert merge.canonical_key({"candidate_id": "TED:123", "title": "A"}) == merge.canonical_key({"candidate_id": "TED:123", "title": "B"})


def test_coverage_guard_requires_exhaustion_for_ted():
    guard = load("coverage_guard_test", "pipeline/source_coverage_guard.py")
    with TemporaryDirectory() as td:
        p = Path(td)
        (p / "stats.json").write_text(json.dumps({"source": "TED", "errors": [], "enumeration_complete": False}), encoding="utf-8")
        h = guard.stats_health(p)
        assert h["status"] == "DEGRADED"
        assert any(x["reason"] == "ENUMERATION_INCOMPLETE" for x in h["problems"])
        (p / "stats.json").write_text(json.dumps({"source": "TED", "errors": [], "enumeration_complete": True}), encoding="utf-8")
        assert guard.stats_health(p)["status"] == "OK"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    payloads = []

    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, data=None, timeout=None, **kwargs):
        body = kwargs.get("json")
        if body is None:
            body = json.loads(data)
        self.calls.append(body)
        return FakeResponse(self.payloads.pop(0))


def test_ted_full_active_keeps_old_publication_and_exhausts_iteration():
    ted = load("discover_ted_test", "pipeline/discover_ted.py")
    with TemporaryDirectory() as td:
        ted.OUT = Path(td)
        ted.HARD_MAX_PAGES = 0
        ted.PAGE_DELAY_SECONDS = 0
        ted.FULL_ACTIVE = True
        ted.SCOPE = "ACTIVE"
        ted.QUERY = "form-type = competition"
        FakeSession.payloads = [
            {
                "totalNoticeCount": 2,
                "notices": [
                    {"publication-number": "1-2026", "publication-date": "2026-01-05", "notice-title": "Old but active"}
                ],
                "iterationNextToken": "next-1",
            },
            {
                "totalNoticeCount": 2,
                "notices": [
                    {"publication-number": "2-2026", "publication-date": "2026-08-18", "notice-title": "Fresh"}
                ],
            },
        ]
        with patch.object(ted.requests, "Session", FakeSession):
            stats = ted.run()
        rows = [json.loads(x) for x in (Path(td) / "current.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [r["candidate_id"] for r in rows] == ["TED:1-2026", "TED:2-2026"]
        assert rows[0]["currentness_evidence"] == "TED_ACTIVE_COMPETITION_SCOPE"
        assert stats["enumeration_complete"] is True
        assert stats["enumeration_exhausted"] is True
        assert stats["source_items_seen"] == 2


def test_ted_hard_cap_is_never_called_complete():
    ted = load("discover_ted_cap_test", "pipeline/discover_ted.py")
    with TemporaryDirectory() as td:
        ted.OUT = Path(td)
        ted.HARD_MAX_PAGES = 1
        ted.PAGE_DELAY_SECONDS = 0
        ted.FULL_ACTIVE = True
        ted.SCOPE = "ACTIVE"
        ted.QUERY = "form-type = competition"
        FakeSession.payloads = [
            {
                "totalNoticeCount": 2,
                "notices": [{"publication-number": "1-2026", "notice-title": "A"}],
                "iterationNextToken": "still-more",
            }
        ]
        with patch.object(ted.requests, "Session", FakeSession):
            stats = ted.run()
        assert stats["truncated_by_page_cap"] is True
        assert stats["enumeration_complete"] is False
