from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.discover_de_doe_ocds import (
    FIRST_FULL_MONTH,
    add_month,
    delta_month_manifest,
    full_month_manifest,
    iter_releases,
)


def test_month_math_and_full_manifest_are_gapless():
    assert FIRST_FULL_MONTH == (2022, 12)
    assert add_month(2022, 12, 1) == (2023, 1)
    assert add_month(2023, 1, -1) == (2022, 12)
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    months = full_month_manifest(now)
    assert months[0] == "2022-12"
    assert months[-1] == "2026-08"
    assert len(months) == 45
    assert len(months) == len(set(months))


def test_delta_manifest_is_recent_and_never_precedes_official_start(monkeypatch):
    monkeypatch.setattr("pipeline.discover_de_doe_ocds.DELTA_MONTHS", 3)
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert delta_month_manifest(now) == ["2026-06", "2026-07", "2026-08"]

    early = datetime(2022, 12, 20, tzinfo=timezone.utc)
    assert delta_month_manifest(early) == ["2022-12"]


def test_iter_releases_accepts_release_package_direct_release_and_list():
    a = {"ocid": "ocds-a", "id": "a", "tender": {"title": "A"}}
    b = {"ocid": "ocds-b", "id": "b", "tender": {"title": "B"}}
    assert list(iter_releases({"releases": [a, b]})) == [a, b]
    assert list(iter_releases(a)) == [a]
    assert list(iter_releases([{"releases": [a]}, b])) == [a, b]


def test_full_manifest_matches_official_start_through_current_month():
    now = datetime.now(timezone.utc)
    months = full_month_manifest(now)
    assert months[0] == "2022-12"
    assert months[-1] == f"{now.year:04d}-{now.month:02d}"
