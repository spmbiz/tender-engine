from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_lt():
    spec = importlib.util.spec_from_file_location("discover_lt_test", ROOT / "pipeline/discover_lt_cvp_api.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def row(i: int, deadline: str = "01-01-2099 12:00:00"):
    return {"id": str(i), "title": f"Tender {i}", "tenderSubmissionDeadline": deadline}


def test_legacy_page_cap_is_ignored_by_default_and_short_page_proves_exhaustion(tmp_path: Path, monkeypatch):
    lt = load_lt()
    pages = {1: [row(1), row(2)], 2: [row(3)]}
    monkeypatch.delenv("LT_CVP_ALLOW_PAGE_CAP", raising=False)
    monkeypatch.setattr(lt, "fetch_page", lambda session, *, page_num, page_size: pages.get(page_num, []))
    monkeypatch.setattr(sys, "argv", ["lt", "--output", str(tmp_path), "--page-size", "2", "--max-pages", "1", "--max-runtime-seconds", "600"])
    lt.main()
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["page_cap_enabled"] is False
    assert stats["pages_fetched"] == 2
    assert stats["enumeration_exhausted"] is True
    assert stats["enumeration_complete"] is True
    assert stats["truncated_by_page_cap"] is False
    assert stats["current_materialized"] == 3


def test_explicit_emergency_page_cap_stays_incomplete(tmp_path: Path, monkeypatch):
    lt = load_lt()
    monkeypatch.setenv("LT_CVP_ALLOW_PAGE_CAP", "1")
    monkeypatch.setattr(lt, "fetch_page", lambda session, *, page_num, page_size: [row(page_num * 10 + 1), row(page_num * 10 + 2)])
    monkeypatch.setattr(sys, "argv", ["lt", "--output", str(tmp_path), "--page-size", "2", "--max-pages", "1", "--max-runtime-seconds", "600"])
    lt.main()
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["page_cap_enabled"] is True
    assert stats["pages_fetched"] == 1
    assert stats["truncated_by_page_cap"] is True
    assert stats["enumeration_complete"] is False
