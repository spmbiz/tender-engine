from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")


def build(tmp_path: Path, current_rows, previous_rows):
    current = tmp_path / "current.jsonl"
    previous = tmp_path / "previous.jsonl"
    previous_manifest = tmp_path / "previous_manifest.json"
    out = tmp_path / "out"
    write_jsonl(current, current_rows)
    write_jsonl(previous, previous_rows)
    previous_manifest.write_text(json.dumps({"source_discovery_run": 111}), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "pipeline/build_live_world_snapshot.py"),
            "--input", str(current),
            "--previous", str(previous),
            "--previous-manifest", str(previous_manifest),
            "--out-dir", str(out),
            "--source-run", "222",
            "--packet-size", "50",
        ],
        cwd=ROOT,
        check=True,
    )
    rows = [json.loads(x) for x in (out / "live_open_tenders.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    manifest = json.loads((out / "snapshot_manifest.json").read_text(encoding="utf-8"))
    return rows, manifest


def test_future_deadline_is_carried_even_without_source_regression(tmp_path: Path):
    rows, manifest = build(
        tmp_path,
        [{"candidate_id": "US-SAM:NOW", "source": "US_SAM", "title": "Current", "deadline": "2099-09-01T00:00:00+00:00"}],
        [{"candidate_id": "TED:OLD", "source": "TED", "title": "Still live", "deadline": "2099-10-01T00:00:00+00:00"}],
    )
    ids = {r["candidate_id"] for r in rows}
    assert ids == {"US-SAM:NOW", "TED:OLD"}
    carried = next(r for r in rows if r["candidate_id"] == "TED:OLD")
    assert carried["carry_forward_reason"] == "FUTURE_DEADLINE_NOT_REOBSERVED"
    assert carried["carried_forward_from_previous_snapshot"] is True
    assert manifest["carried_forward_rows"] == 1
    assert manifest["previous_source_run"] == 111


def test_source_collapse_carries_unknown_deadlines_but_not_expired(tmp_path: Path):
    previous = [
        {"candidate_id": f"TED:{i}", "source": "TED", "title": f"Unknown {i}"}
        for i in range(5)
    ] + [
        {"candidate_id": "TED:EXPIRED", "source": "TED", "title": "Expired", "deadline": "2020-01-01T00:00:00+00:00"}
    ]
    rows, manifest = build(
        tmp_path,
        [{"candidate_id": "US-SAM:NOW", "source": "US_SAM", "title": "Current", "deadline": "2099-09-01T00:00:00+00:00"}],
        previous,
    )
    ids = {r["candidate_id"] for r in rows}
    assert all(f"TED:{i}" in ids for i in range(5))
    assert "TED:EXPIRED" not in ids
    assert manifest["source_regressions_guarded"]["TED"]["current_materialized"] == 0
    assert manifest["carry_forward_reasons"]["SOURCE_REGRESSION_UNKNOWN_DEADLINE"] == 5


def test_healthy_source_does_not_keep_unknown_rows_forever(tmp_path: Path):
    previous = [{"candidate_id": f"FR:{i}", "source": "FR", "title": f"Old {i}"} for i in range(10)]
    current = [{"candidate_id": f"FR:{i}", "source": "FR", "title": f"Now {i}"} for i in range(8)]
    rows, manifest = build(tmp_path, current, previous)
    assert {r["candidate_id"] for r in rows} == {f"FR:{i}" for i in range(8)}
    assert "FR" not in manifest["source_regressions_guarded"]
    assert manifest["carried_forward_rows"] == 0
