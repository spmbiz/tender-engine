from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{rel}: expected exactly one patch anchor, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def append_once(rel: str, marker: str, payload: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + payload.rstrip() + "\n", encoding="utf-8")


def patch_ted() -> None:
    rel = "pipeline/discover_ted.py"
    replace_once(
        rel,
        '''    truncated_by_page_cap = False\n    exhausted = False\n\n    page_no = 0\n''',
        '''    truncated_by_page_cap = False\n    exhausted = False\n\n    # Durable per-page checkpoints are intentionally written before the next API\n    # request. If GitHub terminates a long ACTIVE traversal, the workflow can\n    # still persist the partial pack and coverage truth instead of losing the\n    # entire TED lane. A checkpoint is never allowed to claim completeness.\n    active_path = OUT / "active.jsonl"\n    current_path = OUT / "current.jsonl"\n    stats_path = OUT / "stats.json"\n    active_path.write_text("", encoding="utf-8")\n    current_path.write_text("", encoding="utf-8")\n\n    def checkpoint(state: str, *, next_token_present: bool = False) -> None:\n        current_count = sum(1 for r in rows if r.get("current"))\n        payload = {\n            "source": "TED",\n            "scope": SCOPE,\n            "enumeration_mode": "FULL_ACTIVE_COMPETITION" if FULL_ACTIVE else "RECENT_PUBLICATION_WINDOW",\n            "query": QUERY,\n            "lookback_days": None if FULL_ACTIVE else LOOKBACK_DAYS,\n            "window_start_day": None if FULL_ACTIVE else START_DAY.isoformat(),\n            "window_end_day": NOW.date().isoformat(),\n            "pages": page_count,\n            "limit": LIMIT,\n            "hard_max_pages": HARD_MAX_PAGES,\n            "total_reported": total_reported,\n            "source_items_seen": source_items_seen,\n            "materialized_unique": len(rows),\n            "current_materialized": current_count,\n            "future_deadline_records": sum(1 for r in rows if r.get("has_future_deadline")),\n            "enumeration_exhausted": False,\n            "enumeration_complete": False,\n            "truncated_by_page_cap": truncated_by_page_cap,\n            "request_retries": REQUEST_RETRIES,\n            "page_delay_seconds": PAGE_DELAY_SECONDS,\n            "retry_events": retry_events,\n            "rate_limit_events": sum(1 for x in retry_events if x.get("status") == 429),\n            "errors": errors,\n            "checkpoint": True,\n            "checkpoint_state": state,\n            "next_token_present": bool(next_token_present),\n            "generated_at": datetime.now(timezone.utc).isoformat(),\n            "semantics": "Checkpoint only: partial TED ACTIVE traversal is durable but never complete until iteration-token exhaustion is proven.",\n        }\n        tmp = OUT / "stats.json.tmp"\n        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")\n        tmp.replace(stats_path)\n\n    checkpoint("STARTED")\n\n    page_no = 0\n''',
    )
    replace_once(
        rel,
        '''        source_items_seen += len(items)\n\n        for item in items:\n''',
        '''        source_items_seen += len(items)\n        page_row_start = len(rows)\n\n        for item in items:\n''',
    )
    replace_once(
        rel,
        '''        next_token = data.get("iterationNextToken") or data.get("nextToken") or data.get("nextPageToken")\n        if not next_token or not items:\n            exhausted = True\n            token = None\n            break\n        token = next_token\n        if PAGE_DELAY_SECONDS:\n            time.sleep(PAGE_DELAY_SECONDS)\n\n    with (OUT / "active.jsonl").open("w", encoding="utf-8") as f:\n        for rec in rows:\n            f.write(json.dumps(rec, ensure_ascii=False) + "\\n")\n\n    current_rows = [r for r in rows if r.get("current")]\n    with (OUT / "current.jsonl").open("w", encoding="utf-8") as f:\n        for rec in current_rows:\n            f.write(json.dumps(rec, ensure_ascii=False) + "\\n")\n''',
        '''        page_rows = rows[page_row_start:]\n        if page_rows:\n            with active_path.open("a", encoding="utf-8") as f:\n                for rec in page_rows:\n                    f.write(json.dumps(rec, ensure_ascii=False) + "\\n")\n            with current_path.open("a", encoding="utf-8") as f:\n                for rec in page_rows:\n                    if rec.get("current"):\n                        f.write(json.dumps(rec, ensure_ascii=False) + "\\n")\n\n        next_token = data.get("iterationNextToken") or data.get("nextToken") or data.get("nextPageToken")\n        if not next_token or not items:\n            exhausted = True\n            token = None\n            checkpoint("EXHAUSTED", next_token_present=False)\n            break\n        token = next_token\n        checkpoint("PAGE_COMMITTED", next_token_present=True)\n        if PAGE_DELAY_SECONDS:\n            time.sleep(PAGE_DELAY_SECONDS)\n\n    current_rows = [r for r in rows if r.get("current")]\n''',
    )
    replace_once(
        rel,
        '''    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")\n''',
        '''    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")\n''',
    )


def patch_discovery_workflow() -> None:
    rel = ".github/workflows/supergreen-discovery-v2.yml"
    replace_once(
        rel,
        '''  ted-discovery:\n    needs: init-release\n    runs-on: ubuntu-latest\n    timeout-minutes: 15\n''',
        '''  ted-discovery:\n    needs: init-release\n    runs-on: ubuntu-latest\n    # Full TED ACTIVE enumeration is deliberately uncapped. Keep enough job\n    # budget for exhaustion while leaving a margin after the enumeration step\n    # to persist a checkpoint pack even if that step times out.\n    timeout-minutes: 70\n''',
    )
    replace_once(
        rel,
        '''      - name: Enumerate TED with delta/reconcile safety window\n        env:\n''',
        '''      - name: Enumerate complete TED ACTIVE registry\n        timeout-minutes: 55\n        env:\n''',
    )
    replace_once(rel, "          TED_PAGE_DELAY_SECONDS: '0.25'\n", "          TED_PAGE_DELAY_SECONDS: '0.05'\n")
    replace_once(
        rel,
        '''      - name: Persist TED discovery durably BEFORE completeness validation\n        env: {GH_TOKEN: '${{ github.token }}', RELEASE_TAG: '${{ needs.init-release.outputs.release_tag }}'}\n''',
        '''      - name: Persist TED discovery durably BEFORE completeness validation\n        if: always()\n        env: {GH_TOKEN: '${{ github.token }}', RELEASE_TAG: '${{ needs.init-release.outputs.release_tag }}'}\n''',
    )
    replace_once(
        rel,
        '''      - name: Verify TED coverage integrity\n        run: |\n          python - <<'PY'\n          import json\n          s=json.load(open('discovery/ted/stats.json'));print(json.dumps(s,indent=2))\n          assert not s.get('errors'),s\n          assert not s.get('truncated_by_page_cap'),s\n          if s.get('total_reported') is not None: assert s.get('source_items_seen',0)>=s['total_reported'],s\n          PY\n''',
        '''      - name: Verify TED coverage integrity\n        if: always()\n        run: |\n          python - <<'PY'\n          import json\n          s=json.load(open('discovery/ted/stats.json'));print(json.dumps(s,indent=2))\n          assert not s.get('errors'),s\n          assert not s.get('truncated_by_page_cap'),s\n          assert s.get('enumeration_complete') is True,s\n          if s.get('total_reported') is not None: assert s.get('source_items_seen',0)>=s['total_reported'],s\n          PY\n''',
    )
    # Cyprus/Malta currently emit useful stats before exiting non-zero on an empty\n    # parse. Persist those stats so coverage reports DEGRADED instead of pretending\n    # the pack never existed.
    replace_once(
        rel,
        '''      - name: Persist ePPS source durably\n        env: {GH_TOKEN: '${{ github.token }}', RELEASE_TAG: '${{ needs.init-release.outputs.release_tag }}'}\n''',
        '''      - name: Persist ePPS source durably\n        if: always()\n        env: {GH_TOKEN: '${{ github.token }}', RELEASE_TAG: '${{ needs.init-release.outputs.release_tag }}'}\n''',
    )


def patch_snapshot_builder() -> None:
    rel = "pipeline/build_live_world_snapshot.py"
    replace_once(
        rel,
        '''    ap.add_argument("--source-run", required=True)\n    ap.add_argument("--packet-size", type=int, default=500)\n    args = ap.parse_args()\n''',
        '''    ap.add_argument("--source-run", required=True)\n    ap.add_argument("--packet-size", type=int, default=500)\n    ap.add_argument("--previous", help="Previous normalized live snapshot JSONL(.gz) used only as a high-recall continuity guard")\n    ap.add_argument("--previous-manifest", help="Previous snapshot manifest, for provenance only")\n    ap.add_argument("--source-regression-ratio", type=float, default=0.70)\n    ap.add_argument("--source-regression-min-rows", type=int, default=5)\n    args = ap.parse_args()\n''',
    )
    replace_once(
        rel,
        '''            seen_ids.add(cid)\n            rows.append(row)\n\n    rows.sort(key=lambda r: (r.get("deadline_utc") or "9999", r.get("source_family") or "", r.get("candidate_id") or ""))\n''',
        '''            seen_ids.add(cid)\n            rows.append(row)\n\n    # Continuity guard: a transient source failure must not erase a tender that\n    # was previously observed and still has a future deadline. For rows without\n    # a parseable deadline, carry forward only when that source has materially\n    # regressed versus the previous snapshot. Carried rows are explicit and never\n    # upgrade coverage truth or eligibility.\n    current_materialized_rows = len(rows)\n    current_by_source = Counter(str(r.get("source_family") or "UNKNOWN") for r in rows)\n    previous_rows: list[dict[str, Any]] = []\n    previous_by_source: Counter[str] = Counter()\n    previous_source_run: Any = None\n    previous_path = Path(args.previous) if args.previous else None\n    if previous_path and previous_path.exists() and previous_path.stat().st_size:\n        opener = gzip.open if previous_path.suffix == ".gz" else open\n        with opener(previous_path, "rt", encoding="utf-8", errors="replace") as f:\n            for line in f:\n                if not line.strip():\n                    continue\n                try:\n                    prev = json.loads(line)\n                except Exception:\n                    continue\n                if not isinstance(prev, dict):\n                    continue\n                cid = str(prev.get("candidate_id") or "").strip()\n                if not cid:\n                    continue\n                deadline_dt = parse_dt(prev.get("deadline_utc") or prev.get("deadline"))\n                if deadline_dt and deadline_dt <= now:\n                    continue\n                family = str(prev.get("source_family") or source_family(prev, cid) or "UNKNOWN")\n                prev = dict(prev)\n                prev["source_family"] = family\n                previous_rows.append(prev)\n                previous_by_source[family] += 1\n\n    if args.previous_manifest:\n        try:\n            pm = json.loads(Path(args.previous_manifest).read_text(encoding="utf-8"))\n            previous_source_run = pm.get("source_discovery_run")\n        except Exception:\n            previous_source_run = None\n\n    ratio = min(0.99, max(0.05, float(args.source_regression_ratio)))\n    min_rows = max(1, int(args.source_regression_min_rows))\n    source_regressions: dict[str, dict[str, Any]] = {}\n    for family, previous_count in previous_by_source.items():\n        current_count = int(current_by_source.get(family, 0))\n        if previous_count >= min_rows and current_count < previous_count * ratio:\n            source_regressions[family] = {\n                "previous_unexpired_or_unknown": previous_count,\n                "current_materialized": current_count,\n                "ratio": (current_count / previous_count) if previous_count else 0.0,\n            }\n\n    carry_forward_reasons: Counter[str] = Counter()\n    carried_by_source: Counter[str] = Counter()\n    for prev in previous_rows:\n        cid = str(prev.get("candidate_id") or "").strip()\n        if not cid or cid in seen_ids:\n            continue\n        family = str(prev.get("source_family") or "UNKNOWN")\n        deadline_dt = parse_dt(prev.get("deadline_utc") or prev.get("deadline"))\n        if deadline_dt and deadline_dt > now:\n            reason = "FUTURE_DEADLINE_NOT_REOBSERVED"\n        elif family in source_regressions:\n            reason = "SOURCE_REGRESSION_UNKNOWN_DEADLINE"\n        else:\n            continue\n        row = dict(prev)\n        row["carried_forward_from_previous_snapshot"] = True\n        row["carry_forward_reason"] = reason\n        row["carry_forward_previous_source_run"] = previous_source_run\n        if deadline_dt:\n            row["deadline_utc"] = deadline_dt.isoformat()\n            row["open_state"] = "OPEN_CONFIRMED_BY_DEADLINE"\n        else:\n            row["open_state"] = "OPEN_UNVERIFIED_NO_PARSEABLE_DEADLINE"\n        seen_ids.add(cid)\n        rows.append(row)\n        carry_forward_reasons[reason] += 1\n        carried_by_source[family] += 1\n\n    rows.sort(key=lambda r: (r.get("deadline_utc") or "9999", r.get("source_family") or "", r.get("candidate_id") or ""))\n''',
    )
    replace_once(
        rel,
        '''        "rule": "Contains every canonical discovery row not proven expired by a parseable deadline. Missing/unparseable deadline remains explicitly OPEN_UNVERIFIED; it is never silently treated as confirmed open.",\n        "raw_canonical_rows": raw_count,\n        "snapshot_rows": len(rows),\n''',
        '''        "rule": "Contains every current canonical discovery row not proven expired, plus explicit high-recall carry-forward from the previous snapshot for still-future deadlines and materially regressed source lanes. Carry-forward never upgrades coverage truth or eligibility.",\n        "raw_canonical_rows": raw_count,\n        "current_materialized_rows": current_materialized_rows,\n        "previous_snapshot_rows_considered": len(previous_rows),\n        "previous_source_run": previous_source_run,\n        "carried_forward_rows": sum(carry_forward_reasons.values()),\n        "carry_forward_reasons": dict(carry_forward_reasons),\n        "carried_forward_by_source": dict(carried_by_source.most_common()),\n        "source_regressions_guarded": source_regressions,\n        "snapshot_rows": len(rows),\n''',
    )


def patch_snapshot_workflow() -> None:
    rel = ".github/workflows/live-world-snapshot.yml"
    replace_once(
        rel,
        '''          echo "WIDE_READ_ASSET=$asset" >> "$GITHUB_ENV"\n\n      - name: Build fail-closed open-tender snapshot and GPT packets\n''',
        '''          echo "WIDE_READ_ASSET=$asset" >> "$GITHUB_ENV"\n\n          # Recover the previously published normalized universe before replacing\n          # the stable tag. The builder uses it only as an explicit continuity\n          # guard; current discovery remains authoritative when present.\n          mkdir -p previous-snapshot\n          echo "PREVIOUS_SNAPSHOT_PATH=" >> "$GITHUB_ENV"\n          echo "PREVIOUS_SNAPSHOT_MANIFEST=" >> "$GITHUB_ENV"\n          if gh release view live-world-snapshot-latest >/dev/null 2>&1; then\n            latest_assets="$(gh release view live-world-snapshot-latest --json assets --jq '.assets[].name')"\n            if grep -Fxq live-open-tenders-latest.jsonl.gz <<< "$latest_assets" && grep -Fxq snapshot-manifest-latest.json <<< "$latest_assets"; then\n              gh release download live-world-snapshot-latest \\\n                --pattern live-open-tenders-latest.jsonl.gz \\\n                --pattern snapshot-manifest-latest.json \\\n                --dir previous-snapshot --clobber\n              echo "PREVIOUS_SNAPSHOT_PATH=previous-snapshot/live-open-tenders-latest.jsonl.gz" >> "$GITHUB_ENV"\n              echo "PREVIOUS_SNAPSHOT_MANIFEST=previous-snapshot/snapshot-manifest-latest.json" >> "$GITHUB_ENV"\n            fi\n          fi\n\n      - name: Build fail-closed open-tender snapshot and GPT packets\n''',
    )
    replace_once(
        rel,
        '''          python pipeline/build_live_world_snapshot.py \\\n            --input "$CANDIDATES_PATH" \\\n            --out-dir live-snapshot \\\n            --source-run "$SOURCE_RUN" \\\n            --packet-size 500\n''',
        '''          previous=()\n          if [ -n "${PREVIOUS_SNAPSHOT_PATH:-}" ] && [ -s "$PREVIOUS_SNAPSHOT_PATH" ]; then\n            previous+=(--previous "$PREVIOUS_SNAPSHOT_PATH")\n            if [ -n "${PREVIOUS_SNAPSHOT_MANIFEST:-}" ] && [ -s "$PREVIOUS_SNAPSHOT_MANIFEST" ]; then\n              previous+=(--previous-manifest "$PREVIOUS_SNAPSHOT_MANIFEST")\n            fi\n          fi\n          python pipeline/build_live_world_snapshot.py \\\n            --input "$CANDIDATES_PATH" \\\n            --out-dir live-snapshot \\\n            --source-run "$SOURCE_RUN" \\\n            --packet-size 500 \\\n            "${previous[@]}"\n''',
    )
    replace_once(
        rel,
        '''          # Derive a transparent list where schemas expose source rows/statuses.\n          failed=[]\n          for container_key in ('sources','source_status','source_coverage','measurements','lanes'):\n''',
        '''          # Derive a transparent list from both the V4 coverage guard's\n          # top-level missing/degraded lanes and any older nested status schemas.\n          failed=[]\n          for key in ('missing_packs','degraded_packs','external_missing_lanes'):\n              vals=cov.get(key)\n              if isinstance(vals,list): failed.extend(str(x) for x in vals if str(x).strip())\n          for container_key in ('sources','source_status','source_coverage','measurements','lanes'):\n''',
    )
    replace_once(
        rel,
        '''          m['coverage_rule']='Snapshot completeness is bounded by the measured discovery coverage manifest. Failed/unknown source lanes remain explicit and are never represented as zero or successfully harvested.'\n''',
        '''          m['coverage_rule']='Snapshot completeness is bounded by measured discovery coverage. Failed/unknown lanes remain explicit. High-recall carry-forward may preserve previously observed still-live rows, but never converts a missing/degraded source into successful current coverage.'\n''',
    )
    replace_once(
        rel,
        "            'rule':'GPT selects candidate IDs semantically; GitHub retrieves DCE only after selection. Failed source lanes remain missing/UNKNOWN. No notice-only FINAL_SUPER_GREEN.'\n",
        "            'rule':'GPT selects candidate IDs semantically; GitHub retrieves DCE only after selection. Coverage gaps stay explicit even when prior still-live rows are carried forward for recall. No notice-only FINAL_SUPER_GREEN.'\n",
    )


def patch_qwen_recall_budget() -> None:
    rel = "pipeline/build_qwen_dce_selection_coded.py"
    replace_once(rel, "    ap.add_argument('--explore-share', type=float, default=.20)\n", "    ap.add_argument('--explore-share', type=float, default=.30)\n")
    replace_once(rel, "    ap.add_argument('--reject-audit-share', type=float, default=.05)\n", "    ap.add_argument('--reject-audit-share', type=float, default=.20)\n")
    replace_once(
        rel,
        '''        summary.setdefault("policy", {})["procurement_code_prior_never_changes_keep_or_dce_eligible"] = True\n''',
        '''        summary.setdefault("policy", {})["procurement_code_prior_never_changes_keep_or_dce_eligible"] = True\n        summary["policy"]["recall_guard_until_qwen_benchmark_passes"] = {\n            "default_explore_share": float(args.explore_share),\n            "default_reject_audit_share": float(args.reject_audit_share),\n            "reason": "Qwen runtime is still benchmark-blocked; spend more DCE capacity auditing MAYBE/REJECT paths to measure false negatives.",\n        }\n''',
    )


def write_tests() -> None:
    (ROOT / "tests/test_snapshot_carry_forward.py").write_text(r'''from __future__ import annotations

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
''', encoding="utf-8")

    (ROOT / "tests/test_ted_checkpoint.py").write_text(r'''from __future__ import annotations

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

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class InterruptAfterOnePageSession:
    def __init__(self):
        self.headers = {}
        self.calls = 0

    def post(self, url, data=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            return Response({
                "totalNoticeCount": 2,
                "notices": [{"publication-number": "1-2099", "notice-title": "First"}],
                "iterationNextToken": "more",
            })
        raise KeyboardInterrupt("simulate GitHub step termination")


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
''', encoding="utf-8")

    (ROOT / "tests/test_recall_workflow_contract.py").write_text(r'''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ted_workflow_has_checkpoint_persistence_margin():
    text = (ROOT / ".github/workflows/supergreen-discovery-v2.yml").read_text(encoding="utf-8")
    section = text.split("  ted-discovery:", 1)[1].split("  contracts-finder-discovery:", 1)[0]
    assert "timeout-minutes: 70" in section
    assert "timeout-minutes: 55" in section
    assert "Persist TED discovery durably BEFORE completeness validation\n        if: always()" in section
    assert "assert s.get('enumeration_complete') is True" in section


def test_snapshot_workflow_recovers_previous_live_universe():
    text = (ROOT / ".github/workflows/live-world-snapshot.yml").read_text(encoding="utf-8")
    assert "PREVIOUS_SNAPSHOT_PATH" in text
    assert "--previous \"$PREVIOUS_SNAPSHOT_PATH\"" not in text  # args are safely assembled as a bash array
    assert 'previous+=(--previous "$PREVIOUS_SNAPSHOT_PATH")' in text
    assert "('missing_packs','degraded_packs','external_missing_lanes')" in text


def test_qwen_defaults_spend_more_capacity_on_false_negative_audits():
    text = (ROOT / "pipeline/build_qwen_dce_selection_coded.py").read_text(encoding="utf-8")
    assert "--explore-share', type=float, default=.30" in text
    assert "--reject-audit-share', type=float, default=.20" in text
    assert "recall_guard_until_qwen_benchmark_passes" in text
''', encoding="utf-8")


def main() -> None:
    patch_ted()
    patch_discovery_workflow()
    patch_snapshot_builder()
    patch_snapshot_workflow()
    patch_qwen_recall_budget()
    write_tests()
    print("P0 recall hardening patch applied")


if __name__ == "__main__":
    main()
