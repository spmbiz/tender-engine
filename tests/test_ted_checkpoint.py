from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_ted():
    spec = importlib.util.spec_from_file_location("discover_ted_checkpoint_test", ROOT / "pipeline/discover_ted.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class InterruptAfterOnePageSession:
    def __init__(self):
        self.headers = {}
        self.calls = 0

    def post(self, url, data=None, timeout=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return Response({
                "totalNoticeCount": 2,
                "notices": [{"publication-number": "1-2099", "notice-title": "First"}],
                "iterationNextToken": "more",
            })
        raise KeyboardInterrupt("simulate runner step termination")


def test_ted_page_checkpoint_survives_abrupt_termination():
    ted = load_ted()
    with TemporaryDirectory() as td:
        ted.OUT = Path(td)
        ted.HARD_MAX_PAGES = 0
        ted.PAGE_DELAY_SECONDS = 0
        ted.FULL_ACTIVE = True
        ted.SCOPE = "ACTIVE"
        ted.QUERY = "form-type = competition"
        with patch.object(ted.requests, "Session", InterruptAfterOnePageSession):
            with pytest.raises(KeyboardInterrupt):
                ted.run()
        stats = json.loads((Path(td) / "stats.json").read_text(encoding="utf-8"))
        rows = [json.loads(x) for x in (Path(td) / "current.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        assert [r["candidate_id"] for r in rows] == ["TED:1-2099"]
        assert stats["checkpoint"] is True
        assert stats["checkpoint_state"] == "PAGE_COMMITTED"
        assert stats["enumeration_complete"] is False
        assert stats["source_items_seen"] == 1
