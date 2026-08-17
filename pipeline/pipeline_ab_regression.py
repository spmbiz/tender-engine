#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

BASELINE_SHA = "98a992d57fbea7f3f23ac68173bca8778a6f8880"
SCHEMA = "TENDER_PIPELINE_AB_REGRESSION_V1"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update({k: str(v) for k, v in env.items()})
    return subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True, timeout=timeout)


def must_run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    cp = run(cmd, cwd=cwd, env=env, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(
            f"command failed rc={cp.returncode} cwd={cwd} cmd={cmd!r}\nstdout:\n{cp.stdout[-6000:]}\nstderr:\n{cp.stderr[-6000:]}"
        )
    return cp


def json_from_stdout(cp: subprocess.CompletedProcess[str]) -> Any:
    text = cp.stdout.strip()
    if not text:
        raise RuntimeError("expected JSON on stdout")
    return json.loads(text)


def capacity_scenario(repo: Path, *, remote_gws: int, active_gws: int, active_tenders: int = 0, requested: int = 60) -> dict[str, Any]:
    code = r'''
import json, os, sys
from collections import Counter
sys.path.insert(0, 'pipeline')
import global_admission as ga
remote_gws=int(os.environ['AB_REMOTE_GWS'])
active_gws=int(os.environ['AB_ACTIVE_GWS'])
active_tenders=int(os.environ['AB_ACTIVE_TENDERS'])
requested=int(os.environ['AB_REQUESTED'])
ga._policy=lambda:{
    'github':{'capacity':20},
    'workloads':{
        'hospitality':{'enabled':False,'weight':0.0,'min_slots_when_demanding':0,'max_slots':0},
        'tenders':{'enabled':True,'weight':0.5,'min_slots_when_demanding':10,'max_slots':20},
        'gws':{'enabled':True,'weight':0.5,'min_slots_when_demanding':10,'max_slots':10},
    },
}
ga._global_state=lambda:{'last_decision':{'demand':{'hospitality':0,'gws':remote_gws,'tenders':100}}}
def state(repo, ignore_run_id=''):
    if repo == ga.GLOBAL_REPO:
        return Counter({'gws':active_gws}), Counter()
    return Counter({'tenders':active_tenders}), Counter()
ga._repo_capacity_state=state
os.environ['GITHUB_REF_NAME']='main'
os.environ.pop('DCE_ADMISSION_PREAUTHORIZED',None)
os.environ.pop('DCE_DISABLE_GLOBAL_ADMISSION',None)
allowed,report=ga.dynamic_tender_parallel(requested)
print(json.dumps({'allowed':allowed,'report':report},sort_keys=True))
'''
    cp = must_run(
        [sys.executable, "-c", code],
        cwd=repo,
        env={
            "AB_REMOTE_GWS": str(remote_gws),
            "AB_ACTIVE_GWS": str(active_gws),
            "AB_ACTIVE_TENDERS": str(active_tenders),
            "AB_REQUESTED": str(requested),
        },
    )
    return json_from_stdout(cp)


def preauthorized_scenario(repo: Path, requested: int = 999) -> dict[str, Any]:
    code = r'''
import json, os, sys
sys.path.insert(0,'pipeline')
import global_admission as ga
os.environ['DCE_ADMISSION_PREAUTHORIZED']='true'
os.environ['GITHUB_REF_NAME']='main'
allowed,report=ga.dynamic_tender_parallel(int(os.environ['AB_REQUESTED']))
print(json.dumps({'allowed':allowed,'report':report},sort_keys=True))
'''
    return json_from_stdout(must_run([sys.executable, "-c", code], cwd=repo, env={"AB_REQUESTED": str(requested)}))


def parse_workflow_default(repo: Path) -> int:
    text = (repo / ".github/workflows/qwen-live-classification.yml").read_text(encoding="utf-8")
    m = re.search(r"per_shard:\s*\n(?:.*\n){0,6}?\s*default:\s*['\"]?(\d+)", text)
    if not m:
        raise RuntimeError("cannot parse qwen per_shard workflow default")
    return int(m.group(1))


def parse_operational_cap(repo: Path) -> int:
    text = (repo / "pipeline/build_qwen_shadow_shards.py").read_text(encoding="utf-8")
    m = re.search(r"DEFAULT_OPERATIONAL_MAX_ROWS_PER_SHARD\s*=\s*(\d+)", text)
    if not m:
        raise RuntimeError("cannot parse Qwen operational shard cap")
    return int(m.group(1))


def scan_preemption(repo: Path) -> list[str]:
    bad: list[str] = []
    root = repo / ".github/workflows"
    for p in sorted(root.glob("qwen-*.yml")):
        text = p.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        dangerous = "gh run cancel" in lowered or "/cancel" in lowered or "actions/runs/${" in lowered and "cancel" in lowered
        automatic = bool(re.search(r"(?m)^\s{2}(push|schedule|workflow_run):", text))
        if dangerous and automatic:
            bad.append(p.name)
    return bad


def make_fixture(path: Path, rows: int = 2400) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for i in range(rows):
            if i < 500:
                reason = "NEW"
                first = now - dt.timedelta(hours=1)
            elif i < 800:
                reason = "UPDATED"
                first = now - dt.timedelta(hours=2)
            elif i < 1300:
                reason = "CLASSIFIER_VERSION_OR_UNCLASSIFIED"
                first = now - dt.timedelta(hours=6)
            else:
                reason = "CLASSIFIER_VERSION_OR_UNCLASSIFIED"
                first = now - dt.timedelta(days=8)
            cid = f"AB:{i:06d}"
            row = {
                "canonical_notice_id": cid,
                "material_fields_hash": f"h{i:06d}",
                "queue_reason": reason,
                "first_seen_at": first.isoformat(),
                "last_seen_at": now.isoformat(),
                "notice": {
                    "candidate_id": cid,
                    "source": "AB_TEST",
                    "country": "IE" if i % 2 == 0 else "UK",
                    "buyer": f"Buyer {i%17}",
                    "title": "Website redesign and hosting" if i % 7 == 0 else "Generic public procurement service",
                    "description": "Design development hosting support digital content" if i % 7 == 0 else "General services",
                    "deadline": (now + dt.timedelta(days=14)).isoformat(),
                },
            }
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def iter_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def shard_run(repo: Path, queue: Path, out_root: Path, *, shards: int, requested_cap: int | None = None, explicit_cap: int | None = None) -> dict[str, Any]:
    out_dir = out_root / "shards"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_root / "manifest.json"
    cmd = [
        sys.executable,
        "pipeline/build_qwen_shadow_shards.py",
        "--input",
        str(queue),
        "--out-dir",
        str(out_dir),
        "--source-run",
        "AB",
        "--shards",
        str(shards),
        "--manifest-out",
        str(manifest),
    ]
    if explicit_cap is not None:
        cmd += ["--max-rows-per-shard", str(explicit_cap)]
    env = {}
    if requested_cap is not None:
        env["REQUESTED_PER_SHARD"] = str(requested_cap)
    must_run(cmd, cwd=repo, env=env, timeout=240)
    m = json.loads(manifest.read_text(encoding="utf-8"))
    ids: set[str] = set()
    rank_counts = {0: 0, 1: 0, 2: 0}
    for p in sorted(out_dir.glob("*.jsonl.gz")):
        for row in iter_gz(p):
            cid = str(row.get("candidate_id") or "")
            if cid:
                if cid in ids:
                    raise RuntimeError(f"duplicate sharded id {cid}")
                ids.add(cid)
            reason = str(row.get("queue_reason") or "").upper()
            if reason in {"NEW", "UPDATED"}:
                rank_counts[0] += 1
            else:
                first = str(row.get("first_seen_at") or "")
                try:
                    d = dt.datetime.fromisoformat(first.replace("Z", "+00:00"))
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=dt.timezone.utc)
                    age = (dt.datetime.now(dt.timezone.utc) - d).total_seconds() / 3600
                    rank_counts[1 if -1 <= age <= 24 else 2] += 1
                except Exception:
                    rank_counts[2] += 1
    return {"manifest": m, "ids": ids, "rank_counts": rank_counts}


def materializer_smoke(repo: Path, work: Path) -> dict[str, Any]:
    candidates = work / "candidates.jsonl"
    selection = work / "selection.jsonl"
    out = work / "materialized.jsonl"
    rows = [
        {
            "candidate_id": "UK_PCS_OCDS:release-123",
            "source": "UK_PCS_OCDS",
            "ocid": "ocds-r6ebe6-ab-test",
            "title": "Website design and development",
            "buyer": "AB Council",
            "deadline": "2099-01-01T12:00:00+00:00",
        },
        {
            "candidate_id": "IE:12345",
            "source": "IRELAND_ETENDERS",
            "notice_id": "12345",
            "title": "Digital content production",
            "buyer": "AB Buyer",
            "deadline": "2099-01-02T12:00:00+00:00",
        },
    ]
    candidates.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    sel = [
        {"candidate_id": "uk_pcs_ocds:ocds-r6ebe6-ab-test", "qwen": {"classification": "STRONG_FIT"}},
        {"candidate_id": "ie:12345", "qwen": {"classification": "FIT"}},
    ]
    selection.write_text("".join(json.dumps(r) + "\n" for r in sel), encoding="utf-8")
    must_run(
        [sys.executable, "pipeline/materialize_dce_selection.py", "--candidates", str(candidates), "--selection", str(selection), "--out", str(out)],
        cwd=repo,
        timeout=120,
    )
    materialized = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    return {"count": len(materialized), "ids": [str(x.get("candidate_id")) for x in materialized]}


def run_targeted_current_tests(repo: Path) -> dict[str, Any]:
    tests = ["tests/test_freshness_conveyor.py", "tests/test_global_admission_preauthorized.py"]
    existing = [x for x in tests if (repo / x).exists()]
    cp = must_run([sys.executable, "-m", "pytest", "-q", *existing], cwd=repo, timeout=240)
    route = None
    route_path = repo / "pipeline/test_dce_worker_v14_routes.py"
    if route_path.exists():
        route_cp = must_run([sys.executable, "pipeline/test_dce_worker_v14_routes.py"], cwd=repo, timeout=120)
        route = route_cp.stdout.strip()[-1000:]
    return {"pytest": cp.stdout.strip()[-2000:], "route_smoke": route}


def live_queue_replay(current: Path, baseline: Path, queue: Path, root: Path) -> dict[str, Any]:
    base = shard_run(baseline, queue, root / "baseline-live", shards=10, explicit_cap=80)
    cur_same = shard_run(current, queue, root / "current-live-same", shards=10, explicit_cap=80)
    cur_fast = shard_run(current, queue, root / "current-live-fast", shards=20, requested_cap=parse_workflow_default(current))
    return {
        "baseline_80": {"selected": len(base["ids"]), "rank_counts": base["rank_counts"], "manifest": base["manifest"]},
        "current_same_80": {"selected": len(cur_same["ids"]), "rank_counts": cur_same["rank_counts"], "manifest": cur_same["manifest"]},
        "current_production_bound": {"selected": len(cur_fast["ids"]), "rank_counts": cur_fast["rank_counts"], "manifest": cur_fast["manifest"]},
        "same_bound_id_equality": base["ids"] == cur_same["ids"],
        "same_bound_baseline_only": sorted(base["ids"] - cur_same["ids"])[:20],
        "same_bound_current_only": sorted(cur_same["ids"] - base["ids"])[:20],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--live-queue")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    current = Path(args.current).resolve()
    baseline = Path(args.baseline).resolve()
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "baseline_sha": BASELINE_SHA,
        "status": "PASS",
        "errors": [],
        "checks": {},
    }

    def check(name: str, fn):
        try:
            report["checks"][name] = fn()
        except Exception as exc:
            report["status"] = "FAIL"
            report["errors"].append({"check": name, "error": repr(exc)})

    def capacity_check():
        base_idle = capacity_scenario(baseline, remote_gws=0, active_gws=0)
        cur_idle = capacity_scenario(current, remote_gws=0, active_gws=0)
        base_gws = capacity_scenario(baseline, remote_gws=10, active_gws=0)
        cur_gws = capacity_scenario(current, remote_gws=10, active_gws=0)
        cur_active = capacity_scenario(current, remote_gws=10, active_gws=6)
        cur_pre = preauthorized_scenario(current)
        if not (0 <= int(cur_idle["allowed"]) <= 20):
            raise AssertionError(cur_idle)
        if int(cur_idle["allowed"]) < int(base_idle["allowed"]):
            raise AssertionError(f"current idle capacity regressed {cur_idle} vs {base_idle}")
        if int(cur_gws["allowed"]) > 10:
            raise AssertionError(f"current steals GWS reservation: {cur_gws}")
        if int(cur_active["allowed"]) + 6 > 20:
            raise AssertionError(f"physical capacity overcommit: {cur_active}")
        if int(cur_pre["allowed"]) > 20:
            raise AssertionError(f"preauthorized hard-cap violated: {cur_pre}")
        return {
            "baseline_idle_allowed": base_idle["allowed"],
            "current_idle_allowed": cur_idle["allowed"],
            "baseline_gws_demand_allowed": base_gws["allowed"],
            "current_gws_demand_allowed": cur_gws["allowed"],
            "current_with_6_active_gws_allowed": cur_active["allowed"],
            "current_preauthorized_999_allowed": cur_pre["allowed"],
        }

    def contract_check():
        workflow_default = parse_workflow_default(current)
        op_cap = parse_operational_cap(current)
        if op_cap < workflow_default:
            raise AssertionError(f"workflow advertises per_shard={workflow_default}, operational sharder silently clamps to {op_cap}")
        qwen = (current / ".github/workflows/qwen-live-classification.yml").read_text(encoding="utf-8")
        if "cancel-in-progress: false" not in qwen:
            raise AssertionError("Qwen live workflow is preemptive")
        bad = scan_preemption(current)
        if bad:
            raise AssertionError(f"automatic legacy Qwen cancellation workflows remain active: {bad}")
        worker = (current / "pipeline/dce_batch_worker.py").read_text(encoding="utf-8")
        if "pipeline/dce_worker_v14.py" not in worker:
            raise AssertionError("production DCE batch worker is not wired to v14")
        return {"workflow_per_shard": workflow_default, "operational_cap": op_cap, "legacy_auto_preemption": bad, "dce_worker": "v14"}

    check("capacity_ab", capacity_check)
    check("workflow_contract", contract_check)

    with tempfile.TemporaryDirectory(prefix="pipeline-ab-") as td:
        root = Path(td)

        def synthetic_replay():
            fixture = root / "fixture.jsonl.gz"
            make_fixture(fixture)
            base = shard_run(baseline, fixture, root / "base-synth", shards=10, explicit_cap=80)
            cur = shard_run(current, fixture, root / "cur-synth", shards=10, explicit_cap=80)
            fast = shard_run(current, fixture, root / "cur-synth-fast", shards=20, requested_cap=parse_workflow_default(current))
            if base["ids"] != cur["ids"]:
                raise AssertionError("same-bound current sharder diverged from frozen baseline on deterministic fixture")
            if len(fast["ids"]) < len(cur["ids"]):
                raise AssertionError("production-bound sharder selected fewer rows than baseline-bound replay")
            if fast["rank_counts"][0] < cur["rank_counts"][0]:
                raise AssertionError("production-bound sharder lost NEW/UPDATED recall")
            return {
                "baseline_selected_80x10": len(base["ids"]),
                "current_selected_80x10": len(cur["ids"]),
                "current_selected_production_bound": len(fast["ids"]),
                "current_production_rank_counts": fast["rank_counts"],
                "production_manifest": fast["manifest"],
            }

        check("synthetic_shard_replay", synthetic_replay)

        def materializer_ab():
            bdir = root / "mat-base"; cdir = root / "mat-cur"
            bdir.mkdir(); cdir.mkdir()
            b = materializer_smoke(baseline, bdir)
            c = materializer_smoke(current, cdir)
            if c["count"] < b["count"] or c["count"] != 2:
                raise AssertionError(f"materializer regression current={c} baseline={b}")
            return {"baseline": b, "current": c}

        check("qwen_to_dce_identity_ab", materializer_ab)

        if args.live_queue:
            q = Path(args.live_queue).resolve()
            if q.exists() and q.stat().st_size > 0:
                def live_ab():
                    x = live_queue_replay(current, baseline, q, root / "live")
                    if not x["same_bound_id_equality"]:
                        raise AssertionError(f"same-bound live replay diverged: {x['same_bound_baseline_only'][:5]} / {x['same_bound_current_only'][:5]}")
                    if x["current_production_bound"]["selected"] < x["baseline_80"]["selected"]:
                        raise AssertionError("production-bound live replay selected fewer rows than frozen baseline replay")
                    if x["current_production_bound"]["rank_counts"][0] < x["baseline_80"]["rank_counts"][0]:
                        raise AssertionError("production-bound live replay lost NEW/UPDATED rows")
                    return x
                check("live_queue_replay", live_ab)

    check("current_targeted_tests", lambda: run_targeted_current_tests(current))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
