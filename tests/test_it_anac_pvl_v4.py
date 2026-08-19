from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.discover_it_anac_pvl_v4 as pvl


def test_reconcile_manifest_starts_at_pvl_launch_and_is_contiguous(monkeypatch):
    monkeypatch.setattr(pvl, "MODE", "reconcile")
    monkeypatch.setattr(pvl, "NOW", datetime(2026, 8, 20, tzinfo=timezone.utc))
    monkeypatch.setattr(pvl, "WINDOW_DAYS", 31)
    windows = pvl.manifest()
    assert windows[0][0] == date(2024, 1, 2)
    assert windows[-1][1] == date(2026, 8, 20)
    for idx, (start, end) in enumerate(windows):
        assert (end - start).days + 1 <= 31
        if idx:
            assert start == windows[idx - 1][1] + pvl.timedelta(days=1)


def test_delta_manifest_is_recent_only(monkeypatch):
    monkeypatch.setattr(pvl, "MODE", "delta")
    monkeypatch.setattr(pvl, "NOW", datetime(2026, 8, 20, tzinfo=timezone.utc))
    monkeypatch.setattr(pvl, "DELTA_LOOKBACK_DAYS", 45)
    windows = pvl.manifest()
    assert windows[0][0] == date(2026, 7, 6)
    assert windows[-1][1] == date(2026, 8, 20)


def _item(deadline: str | None, *, active=True, obscured=False):
    return {
        "idAvviso": "notice-1",
        "idAppalto": "proc-1",
        "dataPubblicazione": "2026-08-19T08:00:00+00:00",
        "dataScadenza": deadline,
        "attivo": active,
        "oscurato": obscured,
        "templates": [{
            "lingua": "it",
            "template": {
                "metadata": {"titolo": "Servizio digitale", "descrizione": "Test"},
                "sections": [],
            },
        }],
    }


def test_normalize_promotes_only_future_deadline_active(monkeypatch):
    monkeypatch.setattr(pvl, "NOW", datetime(2026, 8, 20, tzinfo=timezone.utc))
    live = pvl.normalize(_item("2026-09-01T10:00:00+00:00"))
    assert live is not None and live["current"] is True

    expired = pvl.normalize(_item("2026-08-19T10:00:00+00:00"))
    assert expired is not None and expired["current"] is False

    unknown = pvl.normalize(_item(None))
    assert unknown is not None and unknown["current"] is False
    assert unknown["currentness_evidence"] == "ANAC_PVL_DEADLINE_UNKNOWN_RADAR_ONLY"

    inactive = pvl.normalize(_item("2026-09-01T10:00:00+00:00", active=False))
    assert inactive is not None and inactive["current"] is False

    assert pvl.normalize(_item("2026-09-01T10:00:00+00:00", obscured=True)) is None
