from __future__ import annotations

import argparse
import json
import os
from datetime import timedelta
from pathlib import Path

import fleet_controller as fc

STATE_SCHEMA_VERSION = 3
MAX_REMEMBERED_CANDIDATES = 100_000
MAX_REMEMBERED_DISCOVERY_RUNS = 1_000
DCE_BRANCH = "fleet-dce"


def _emit_output(name: str, value: str):
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def _dedupe(values):
    return list(dict.fromkeys(str(x) for x in values if str(x).strip()))


def _migrate_state(state: dict, actions: list[dict]):
    version = int(state.get("schema_version") or 0)
    if version >= STATE_SCHEMA_VERSION:
        return
    state["schema_version"] = STATE_SCHEMA_VERSION
    state.setdefault("pending_dce_batch", None)
    actions.append({"type": "state_migration", "from_schema": version, "to_schema": STATE_SCHEMA_VERSION})


def _set_branch(branch: str, sha: str):
    path = f"/repos/{fc.REPO}/git/refs/heads/{branch}"
    try:
        fc.api(path, method="PATCH", json={"sha": sha, "force": True})
    except Exception:
        fc.api(
            f"/repos/{fc.REPO}/git/refs",
            method="POST",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )


def _dispatch_dce(ref: str, inputs: dict):
    fc.api(
        f"/repos/{fc.REPO}/actions/workflows/dce-fanout-v2.yml/dispatches",
        method="POST",
        json={"ref": ref, "inputs": inputs},
    )


def _usable_discovery(run_id: str):
    try:
        rel = fc.get_release(f"discovery-harvest-{run_id}")
        if not rel:
            return None
        assets = {str(x.get("name") or "") for x in rel.get("assets", [])}
        repaired = f"supergreen-wide-read-{run_id}-repaired.tar.gz"
        normal = f"supergreen-wide-read-{run_id}.tar.gz"
        asset = repaired if repaired in assets else normal if normal in assets else None
        if not asset:
            return None
        return {"id": run_id, "release": rel, "asset": asset}
    except Exception:
        return None


def _pick_discovery(state: dict):
    active = str(state.get("active_discovery_run_id") or "").strip()
    completed = {str(x) for x in state.get("processed_discovery_runs", [])}
    if active and active not in completed:
        usable = _usable_discovery(active)
        if usable:
            return usable
    latest = fc.latest_usable_discovery()
    if latest and str(latest.get("id")) not in completed:
        state["active_discovery_run_id"] = str(latest["id"])
        return latest
    return None


def _match_pending_run(pending: dict):
    run_id = str(pending.get("workflow_run_id") or "").strip()
    if run_id:
        try:
            return fc.api(f"/repos/{fc.REPO}/actions/runs/{run_id}").json()
        except Exception:
            pass
    expected_sha = str(pending.get("queue_commit_sha") or "").strip()
    expected_message = str(pending.get("commit_message") or "").strip()
    for run in fc.workflow_runs("dce-fanout-v2.yml", limit=20):
        if expected_sha and str(run.get("head_sha") or "") == expected_sha:
            pending["workflow_run_id"] = run.get("id")
            return run
        if expected_message and str(run.get("display_title") or "") == expected_message:
            pending["workflow_run_id"] = run.get("id")
            return run
    return None


def _reconcile_pending(state: dict, actions: list[dict]) -> bool:
    pending = state.get("pending_dce_batch")
    if not isinstance(pending, dict) or not pending.get("candidate_ids"):
        state["pending_dce_batch"] = None
        return False
    run = _match_pending_run(pending)
    if run:
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        if status in {"queued", "in_progress", "requested", "waiting", "pending"}:
            state["pending_dce_batch"] = pending
            return True
        if status == "completed" and conclusion == "success":
            merged = list(state.get("processed_candidate_ids", [])) + list(pending.get("candidate_ids", []))
            state["processed_candidate_ids"] = _dedupe(merged)[-MAX_REMEMBERED_CANDIDATES:]
            actions.append({
                "type": "dce_batch_committed",
                "workflow_run_id": run.get("id"),
                "source_run": pending.get("source_run"),
                "candidates": len(pending.get("candidate_ids", [])),
            })
            state["pending_dce_batch"] = None
            return False
        actions.append({
            "type": "dce_batch_returned_to_queue",
            "workflow_run_id": run.get("id"),
            "conclusion": conclusion or "unknown",
            "source_run": pending.get("source_run"),
            "candidates": len(pending.get("candidate_ids", [])),
        })
        state["pending_dce_batch"] = None
        return False
    dispatched_at = fc.parse_ts(pending.get("dispatched_at"))
    if dispatched_at and fc.NOW - dispatched_at > timedelta(minutes=15):
        actions.append({
            "type": "dce_lease_expired_returned_to_queue",
            "source_run": pending.get("source_run"),
            "candidates": len(pending.get("candidate_ids", [])),
        })
        state["pending_dce_batch"] = None
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desired", default="control/desired_state.json")
    ap.add_argument("--providers", default="control/provider_limits.json")
    args = ap.parse_args()

    desired = fc.load_json(Path(args.desired), {})
    providers = fc.load_json(Path(args.providers), {})
    fleet_release = fc.ensure_fleet_release()
    state_raw = fc.download_asset(fleet_release, fc.STATE_ASSET)
    state = json.loads(state_raw.decode()) if state_raw else {}
    state.setdefault("processed_discovery_runs", [])
    state.setdefault("processed_candidate_ids", [])
    state.setdefault("active_discovery_run_id", None)
    state.setdefault("pending_dce_batch", None)
    state.setdefault("last_discovery_dispatch_at", None)
    state.setdefault("last_circleci_tick_at", None)

    actions: list[dict] = []
    errors: list[dict] = []
    _migrate_state(state, actions)

    enabled = bool(desired.get("enabled")) and bool(desired.get("continuous"))
    github_cfg = providers.get("providers", {}).get("github", {})
    limit = int(os.getenv("GITHUB_CONCURRENCY_LIMIT") or github_cfg.get("standard_hosted_concurrency_limit", 20))

    active, queued, fleet_detail = fc.public_fleet_jobs()
    effective_active_after_controller = max(0, active - 1)
    available_after_controller = max(0, limit - effective_active_after_controller)
    capacity_budget = available_after_controller
    selection_stats = None
    circle_tick_sha = ""

    pending_owns_lane = _reconcile_pending(state, actions)

    if enabled:
        dce_cfg = desired.get("dce", {})
        disc_cfg = desired.get("discovery", {})
        discovery = _pick_discovery(state)

        # Compute freshness demand BEFORE DCE allocation. Previously the DCE lane
        # could consume the entire elastic budget and make minimum_free_github_slots
        # a post-hoc check rather than a reservation, starving the live harvester.
        last_disc = fc.parse_ts(state.get("last_discovery_dispatch_at"))
        discovery_due = last_disc is None or fc.NOW - last_disc >= timedelta(
            minutes=int(disc_cfg.get("min_interval_minutes", 360))
        )
        discovery_running = fc.is_workflow_active("supergreen-discovery-v2.yml")
        backlog_pinned_before_dce = bool(state.get("active_discovery_run_id"))
        allow_refresh_while_backlog = bool(disc_cfg.get("allow_refresh_while_backlog", False))
        discovery_eligible_now = (
            bool(disc_cfg.get("enabled", True))
            and discovery_due
            and not discovery_running
            and (not backlog_pinned_before_dce or allow_refresh_while_backlog)
        )
        freshness_reserve = 0
        if discovery_eligible_now:
            freshness_reserve = min(
                max(0, int(disc_cfg.get("minimum_free_github_slots", 4))),
                capacity_budget,
            )
        dce_capacity_budget = max(0, capacity_budget - freshness_reserve)
        if freshness_reserve:
            actions.append({
                "type": "freshness_capacity_reserved",
                "slots": freshness_reserve,
                "available_before_reserve": capacity_budget,
            })

        any_dce_active = fc.is_workflow_active("dce-fanout-v2.yml")
        if discovery and dce_cfg.get("enabled", True) and not pending_owns_lane and not any_dce_active:
            minimum_slots = int(dce_cfg.get("minimum_free_github_slots", 3))
            if dce_capacity_budget >= minimum_slots:
                run_id = str(discovery["id"])
                selected, selection_stats = fc.select_from_discovery(
                    run_id,
                    int(dce_cfg.get("minimum_retrieval_priority", 34)),
                    int(dce_cfg.get("max_candidates_per_cycle", 320)),
                    set(state.get("processed_candidate_ids", [])),
                )
                if selected:
                    controller_run = os.getenv("GITHUB_RUN_ID", "local")
                    queue_path = f"queues/auto_selection_{controller_run}.jsonl"
                    commit_message = f"Autonomous DCE batch {controller_run} from discovery {run_id}"
                    queue_text = "".join(
                        json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n"
                        for x in selected
                    )
                    write_result = fc.update_repo_text(queue_path, queue_text, commit_message)
                    queue_commit_sha = str((write_result.get("commit") or {}).get("sha") or "")
                    if not queue_commit_sha:
                        raise RuntimeError("queue commit SHA missing; refusing uncorrelatable DCE dispatch")
                    _set_branch(DCE_BRANCH, queue_commit_sha)
                    max_parallel = max(1, min(limit, dce_capacity_budget))
                    _dispatch_dce(
                        DCE_BRANCH,
                        {
                            "selection_path": queue_path,
                            "source_discovery_run": run_id,
                            "max_jobs": str(len(selected)),
                            "max_parallel": str(max_parallel),
                            "max_shards": "256",
                            "jobs_per_shard": "2",
                        },
                    )
                    state["pending_dce_batch"] = {
                        "candidate_ids": [x["candidate_id"] for x in selected],
                        "source_run": run_id,
                        "selection_path": queue_path,
                        "queue_commit_sha": queue_commit_sha,
                        "commit_message": commit_message,
                        "dispatched_at": fc.NOW.isoformat(),
                        "max_parallel": max_parallel,
                    }
                    state["active_discovery_run_id"] = run_id
                    capacity_budget = max(0, capacity_budget - max_parallel)
                    actions.append({
                        "type": "dce_batch_leased",
                        "source_run": run_id,
                        "candidates": len(selected),
                        "max_parallel": max_parallel,
                        "queue_commit_sha": queue_commit_sha,
                        "harvest_drained": False,
                    })
                else:
                    completed = list(state.get("processed_discovery_runs", [])) + [run_id]
                    state["processed_discovery_runs"] = completed[-MAX_REMEMBERED_DISCOVERY_RUNS:]
                    state["active_discovery_run_id"] = None
                    actions.append({
                        "type": "discovery_backlog_drained",
                        "source_run": run_id,
                        "minimum_retrieval_priority": int(dce_cfg.get("minimum_retrieval_priority", 34)),
                    })

        # Recompute after any DCE lease but retain the pre-DCE due decision. The
        # reservation guarantees at least min_slots remains for the refresh.
        expected_slots = int(disc_cfg.get("expected_parallel_slots", 19))
        min_slots = int(disc_cfg.get("minimum_free_github_slots", 4))
        discovery_running = fc.is_workflow_active("supergreen-discovery-v2.yml")
        backlog_pinned = bool(state.get("active_discovery_run_id"))
        discovery_capacity_ok = capacity_budget >= min(expected_slots, limit)

        if disc_cfg.get("enabled", True) and discovery_due and not discovery_running and (not backlog_pinned or allow_refresh_while_backlog):
            if discovery_capacity_ok or (capacity_budget >= min_slots and bool(disc_cfg.get("allow_queue_when_partially_free", False))):
                fc.dispatch("supergreen-discovery-v2.yml")
                capacity_budget = max(0, capacity_budget - min(expected_slots, limit))
                state["last_discovery_dispatch_at"] = fc.NOW.isoformat()
                actions.append({
                    "type": "discovery_dispatch",
                    "expected_peak_slots": expected_slots,
                    "freshness_reserve_used": freshness_reserve,
                })

        cc = desired.get("circleci", {})
        last_cc = fc.parse_ts(state.get("last_circleci_tick_at"))
        cc_due = last_cc is None or fc.NOW - last_cc >= timedelta(minutes=int(cc.get("refresh_interval_minutes", 1440)))
        if cc.get("desired_enabled") and cc_due:
            tick = f"tick={fc.NOW.isoformat()}\nreason=autonomous-refresh\n"
            result = fc.update_repo_text(
                cc.get("trigger_file", fc.CIRCLE_TICK_PATH),
                tick,
                f"Trigger CircleCI autonomous refresh {fc.NOW.isoformat()}",
            )
            circle_tick_sha = str((result.get("commit") or {}).get("sha") or "")
            state["last_circleci_tick_at"] = fc.NOW.isoformat()
            actions.append({
                "type": "circleci_tick",
                "max_parallel": int(cc.get("max_parallel", 30)),
                "commit_sha": circle_tick_sha or None,
            })

    state["updated_at"] = fc.NOW.isoformat()
    state["enabled"] = enabled
    state["mode"] = desired.get("mode", "maximum")
    circle_status = fc.circleci_commit_status()

    status = {
        "generated_at": fc.NOW.isoformat(),
        "state_schema_version": state.get("schema_version"),
        "enabled": enabled,
        "mode": desired.get("mode", "maximum"),
        "github": {
            "limit": limit,
            "active_jobs_observed": active,
            "queued_jobs_observed": queued,
            "available_after_controller": available_after_controller,
            "planned_capacity_remaining": capacity_budget,
            "fleet_detail": fleet_detail,
        },
        "backlog": {
            "active_discovery_run_id": state.get("active_discovery_run_id"),
            "processed_candidate_ids": len(state.get("processed_candidate_ids", [])),
            "pending_dce_candidates": len((state.get("pending_dce_batch") or {}).get("candidate_ids", [])),
            "completed_discovery_runs": len(state.get("processed_discovery_runs", [])),
        },
        "circleci": {
            "desired_enabled": desired.get("circleci", {}).get("desired_enabled", False),
            "advertised_max_parallel": desired.get("circleci", {}).get("max_parallel", 30),
            "write_bridge_secret_required": desired.get("circleci", {}).get("write_bridge_secret", "FLEET_GITHUB_TOKEN"),
            "free_plan_verified_for_this_org": providers.get("providers", {}).get("circleci", {}).get("free_plan_verified_for_this_org", False),
            "latest_status": circle_status,
        },
        "actions": actions,
        "selection": selection_stats,
        "errors": errors,
    }

    gpt = {
        "generated_at": fc.NOW.isoformat(),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "harvest_continues_without_gpt": enabled,
        "actions": actions,
        "github_active_jobs": active,
        "github_queued_jobs": queued,
        "active_discovery_backlog": state.get("active_discovery_run_id"),
        "pending_dce_candidates": len((state.get("pending_dce_batch") or {}).get("candidate_ids", [])),
        "circleci_status": circle_status,
        "latest_discovery_processed": state.get("processed_discovery_runs", [])[-1:] or [],
        "gpt_role": "review ambiguous/high-value/final mandatory-gate evidence; deterministic discovery and DCE prefetch continue autonomously",
    }

    old_hist = fc.download_asset(fleet_release, fc.HISTORY_ASSET)
    history = old_hist.decode("utf-8", errors="replace").splitlines() if old_hist else []
    history.append(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    history = history[-500:]

    fc.upload_asset(fleet_release, fc.STATE_ASSET, json.dumps(state, indent=2).encode(), "application/json")
    fc.upload_asset(fleet_release, fc.STATUS_ASSET, json.dumps(status, indent=2).encode(), "application/json")
    fc.upload_asset(fleet_release, fc.GPT_ASSET, json.dumps(gpt, indent=2).encode(), "application/json")
    fc.upload_asset(fleet_release, fc.HISTORY_ASSET, ("\n".join(history) + "\n").encode(), "application/x-ndjson")

    _emit_output("circleci_tick_sha", circle_tick_sha)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
