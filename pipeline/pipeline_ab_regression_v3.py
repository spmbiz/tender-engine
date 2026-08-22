#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pipeline_ab_regression as ab
from pipeline_ab_regression_v2 import scan_real_qwen_preemption

SCHEMA = "TENDER_PIPELINE_AB_REGRESSION_V3"


def current_dce_worker(repo: Path) -> dict[str, Any]:
    batch = repo / "pipeline/dce_batch_worker.py"
    text = batch.read_text(encoding="utf-8")
    matches = re.findall(r"pipeline/(dce_worker_v(\d+)\.py)", text)
    if not matches:
        raise AssertionError("production DCE batch worker does not reference a versioned dce_worker_vN.py")
    versions = sorted({(name, int(version)) for name, version in matches}, key=lambda x: x[1])
    name, version = versions[-1]
    worker_path = repo / "pipeline" / name
    if not worker_path.is_file():
        raise AssertionError(f"production DCE worker target does not exist: {worker_path}")
    return {
        "worker": name,
        "version": version,
        "path": str(worker_path.relative_to(repo)),
        "batch_worker_sha256_not_checked_here": True,
        "quality_gate": "DCE Rollback A/B durable evidence",
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
        "baseline_sha": ab.BASELINE_SHA,
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
        # Capacity A/B must be deterministic and must distinguish two intentional
        # production modes: normal idle borrowing and Qwen-backlog reservation.
        old_backlog = os.environ.get("QWEN_BACKLOG_REMAINING")
        old_workflow = os.environ.get("GITHUB_WORKFLOW")
        try:
            os.environ["QWEN_BACKLOG_REMAINING"] = "0"
            os.environ["GITHUB_WORKFLOW"] = "Tender General Maintenance"
            base_idle = ab.capacity_scenario(baseline, remote_gws=0, active_gws=0)
            cur_idle = ab.capacity_scenario(current, remote_gws=0, active_gws=0)
            base_gws = ab.capacity_scenario(baseline, remote_gws=10, active_gws=0)
            cur_gws = ab.capacity_scenario(current, remote_gws=10, active_gws=0)
            cur_active = ab.capacity_scenario(current, remote_gws=10, active_gws=6)
            cur_pre = ab.preauthorized_scenario(current)

            os.environ["QWEN_BACKLOG_REMAINING"] = "90000"
            os.environ["GITHUB_WORKFLOW"] = "Tender General Maintenance"
            reserved_general = ab.capacity_scenario(current, remote_gws=0, active_gws=0)

            os.environ["GITHUB_WORKFLOW"] = "Qwen Live Notice Classification"
            reserved_qwen = ab.capacity_scenario(current, remote_gws=0, active_gws=0)
            reserved_qwen_with_gws = ab.capacity_scenario(current, remote_gws=10, active_gws=0)
        finally:
            if old_backlog is None:
                os.environ.pop("QWEN_BACKLOG_REMAINING", None)
            else:
                os.environ["QWEN_BACKLOG_REMAINING"] = old_backlog
            if old_workflow is None:
                os.environ.pop("GITHUB_WORKFLOW", None)
            else:
                os.environ["GITHUB_WORKFLOW"] = old_workflow

        if not 0 <= int(cur_idle["allowed"]) <= 20:
            raise AssertionError(cur_idle)
        if int(cur_idle["allowed"]) < int(base_idle["allowed"]):
            raise AssertionError(f"idle capacity regressed without Qwen backlog current={cur_idle} baseline={base_idle}")
        if int(cur_gws["allowed"]) > 10:
            raise AssertionError(f"current steals GWS reservation: {cur_gws}")
        if int(cur_active["allowed"]) + 6 > 20:
            raise AssertionError(f"physical capacity overcommit: {cur_active}")
        if int(cur_pre["allowed"]) > 20:
            raise AssertionError(f"preauthorized hard cap violated: {cur_pre}")

        target = int(reserved_general["report"].get("qwen_semantic_reservation_target") or 0)
        if target != 16:
            raise AssertionError(f"90k Qwen backlog must reserve 16 slots: {reserved_general}")
        if int(reserved_general["allowed"]) > 20 - target:
            raise AssertionError(f"generic Tender work consumes Qwen reservation: {reserved_general}")
        if int(reserved_qwen["allowed"]) < target:
            raise AssertionError(f"Qwen semantic lane cannot consume its reservation: {reserved_qwen}")
        if int(reserved_qwen["allowed"]) > 20:
            raise AssertionError(f"Qwen semantic lane exceeds physical capacity: {reserved_qwen}")
        if int(reserved_qwen_with_gws["allowed"]) > 10:
            raise AssertionError(f"Qwen reservation steals demanded GWS fair-share: {reserved_qwen_with_gws}")

        return {
            "baseline_idle_allowed": base_idle["allowed"],
            "current_idle_no_qwen_backlog_allowed": cur_idle["allowed"],
            "baseline_gws_demand_allowed": base_gws["allowed"],
            "current_gws_demand_allowed": cur_gws["allowed"],
            "current_with_6_active_gws_allowed": cur_active["allowed"],
            "current_preauthorized_999_allowed": cur_pre["allowed"],
            "qwen_backlog_test": 90000,
            "qwen_reservation_target": target,
            "generic_tender_allowed_with_qwen_reservation": reserved_general["allowed"],
            "qwen_semantic_allowed_with_reservation": reserved_qwen["allowed"],
            "qwen_semantic_allowed_with_gws_demand": reserved_qwen_with_gws["allowed"],
        }

    def workflow_contract():
        default = ab.parse_workflow_default(current)
        cap = ab.parse_operational_cap(current)
        if cap < default:
            raise AssertionError(f"workflow advertises per_shard={default}, operational sharder clamps to {cap}")
        qwen = (current / ".github/workflows/qwen-live-classification.yml").read_text(encoding="utf-8")
        if "cancel-in-progress: false" not in qwen:
            raise AssertionError("Qwen live workflow is preemptive")
        bad = scan_real_qwen_preemption(current)
        if bad:
            raise AssertionError(f"automatic actual Qwen preemption remains: {bad}")
        dce = current_dce_worker(current)
        return {
            "workflow_per_shard": default,
            "operational_cap": cap,
            "legacy_auto_preemption": bad,
            "dce_worker": dce,
        }

    check("capacity_ab", capacity_check)
    check("workflow_contract", workflow_contract)

    with tempfile.TemporaryDirectory(prefix="pipeline-ab-v3-") as td:
        root = Path(td)

        def synthetic():
            fixture = root / "fixture.jsonl.gz"
            ab.make_fixture(fixture)
            base = ab.shard_run(baseline, fixture, root / "base", shards=10, explicit_cap=80)
            same = ab.shard_run(current, fixture, root / "same", shards=10, explicit_cap=80)
            fast = ab.shard_run(current, fixture, root / "fast", shards=20, requested_cap=ab.parse_workflow_default(current))
            if base["ids"] != same["ids"]:
                raise AssertionError("same-bound current sharding diverged from rollback")
            if len(fast["ids"]) < len(same["ids"]):
                raise AssertionError("production bound selects fewer rows than rollback-bound current")
            if fast["rank_counts"][0] < same["rank_counts"][0]:
                raise AssertionError("production bound loses NEW/UPDATED recall")
            return {
                "baseline_selected_80x10": len(base["ids"]),
                "current_selected_80x10": len(same["ids"]),
                "current_selected_production_bound": len(fast["ids"]),
                "current_production_rank_counts": fast["rank_counts"],
            }

        check("synthetic_shard_replay", synthetic)

        def identity():
            bdir = root / "mat-base"; cdir = root / "mat-current"
            bdir.mkdir(); cdir.mkdir()
            b = ab.materializer_smoke(baseline, bdir)
            c = ab.materializer_smoke(current, cdir)
            if c["count"] != 2 or c["count"] < b["count"]:
                raise AssertionError(f"Qwen→DCE identity regression current={c} baseline={b}")
            return {"baseline": b, "current": c}

        check("qwen_to_dce_identity_ab", identity)

        if args.live_queue:
            q = Path(args.live_queue).resolve()
            if q.exists() and q.stat().st_size > 0:
                def live_replay():
                    x = ab.live_queue_replay(current, baseline, q, root / "live")
                    if not x["same_bound_id_equality"]:
                        raise AssertionError(
                            f"same-bound live IDs diverged baseline_only={x['same_bound_baseline_only'][:5]} current_only={x['same_bound_current_only'][:5]}"
                        )
                    if x["current_production_bound"]["selected"] < x["baseline_80"]["selected"]:
                        raise AssertionError("production-bound live replay selects fewer rows")
                    if x["current_production_bound"]["rank_counts"][0] < x["baseline_80"]["rank_counts"][0]:
                        raise AssertionError("production-bound live replay loses NEW/UPDATED")
                    return x
                check("live_queue_replay", live_replay)

    check("current_targeted_tests", lambda: ab.run_targeted_current_tests(current))

    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
