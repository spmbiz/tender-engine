from __future__ import annotations

import argparse
import json
import os
from datetime import timedelta
from pathlib import Path

import requests

import fleet_controller as fc

STATE_SCHEMA_VERSION = 3
MAX_REMEMBERED_CANDIDATES = 100_000
MAX_REMEMBERED_DISCOVERY_RUNS = 1_000
DCE_BRANCH = "fleet-dce"


def _usable_discovery(run_id: str):
    rel = fc.get_release(f"discovery-harvest-{run_id}")
    if not rel:
        return None
    names = {a.get("name") for a in rel.get("assets", [])}
    if f"supergreen-wide-read-{run_id}-repaired.tar.gz" in names or f"supergreen-wide-read-{run_id}.tar.gz" in names:
        return {"id": str(run_id)}
    return None


def _pick_discovery(state: dict):
    completed = {str(x) for x in state.get("processed_discovery_runs", [])}
    active_id = str(state.get("active_discovery_run_id") or "").strip()
    if active_id and active_id not in completed:
        active = _usable_discovery(active_id)
        if active:
            return active
        state["active_discovery_run_id"] = None

    latest = fc.latest_usable_discovery()
    if latest and str(latest.get("id")) not in completed:
        state["active_discovery_run_id"] = str(latest["id"])
        return latest
    return None


def _emit_output(name: str, value: str):
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def _set_branch(branch: str, sha: str):
    ref_path = f"/repos/{fc.REPO}/git/refs/heads/{branch}"
    r = requests.get(fc.API + ref_path, headers=fc.HEADERS, timeout=30)
    if r.status_code == 404:
        created = requests.post(
            fc.API + f"/repos/{fc.REPO}/git/refs",
            headers=fc.HEADERS,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
            timeout=30,
        )
        if created.status_code not in (200, 201):
            raise RuntimeError(f"create {branch}: {created.status_code} {created.text[:700]}")
        return
    if r.status_code >= 400:
        raise RuntimeError(f"read {branch}: {r.status_code} {r.text[:700]}")
    updated = requests.patch(
        fc.API + ref_path,
        headers=fc.HEADERS,
        json={"sha": sha, "force": True},
        timeout=30,
    )
    if updated.status_code not in (200, 201):
        raise RuntimeError(f"update {branch}: {updated.status_code} {updated.text[:700]}")


def _dispatch_dce(ref: str, inputs: dict[str, str]):
    payload = {"ref": ref, "inputs": {k: str(v) for k, v in inputs.items()}}
    r = requests.post(
        f"{fc.API}/repos/{fc.REPO}/actions/workflows/dce-fanout-v2.yml/dispatches",
        headers=fc.HEADERS,
        json=payload,
        timeout=30,
    )
    if r.status_code not in (204, 201):
        raise RuntimeError(f"dispatch DCE: {r.status_code} {r.text[:1000]}")


def _dce_runs(limit=40):
    return fc.workflow_runs("dce-fanout-v2.yml", limit=limit)


def _match_pending_run(pending: dict):
    target_sha = str(pending.get("queue_commit_sha") or "")
    target_message = str(pending.get("commit_message") or "")
    for run in _dce_runs(50):
        if run.get("event") != "workflow_dispatch":
            continue
        head_sha = str(run.get("head_sha") or "")
        head_message = str((run.get("head_commit") or {}).get("message") or "")
        if target_sha and head_sha == target_sha:
            return run
        if target_message and head_message == target_message:
            return run
    return None


def _migrate_state(state: dict, actions: list[dict]):
    version = int(state.get("schema_version") or 0)
    if version >= STATE_SCHEMA_VERSION:
        return

    # v1/v2 treated "dispatched" as "processed". Two live integration tests proved
    # why that is unsafe: one batch was rejected by a downstream validator. Requeue
    # all legacy dispatch IDs once rather than silently losing potentially useful work.
    legacy = list(state.get("processed_candidate_ids", []))
    if legacy:
        state["legacy_dispatched_candidate_ids"] = legacy[-10_000:]
        state["processed_candidate_ids"] = []
        actions.append({
            "type": "state_migration_requeue",
            "from_schema": version,
            "to_schema": STATE_SCHEMA_VERSION,
            "candidate_ids_returned_to_queue": len(legacy),
        })
    state["pending_dce_batch"] = None
    state["schema_version"] = STATE_SCHEMA_VERSION


def _reconcile_pending(state: dict, actions: list[dict]) -> bool:
    """Return True while a leased batch still owns the DCE lane."""
    pending = state.get("pending_dce_batch")
    if not isinstance(pending, dict) or not pending.get("candidate_ids"):
        state["pending_dce_batch"] = None
        return False

    run = _match_pending_run(pending)
    if run:
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        if status in {"queued", "in_progress", "requested", "waiting", "pending"}:
            pending["workflow_run_id"] = run.get("id")
            state["pending_dce_batch"] = pending
            return True
        if status == "completed" and conclusion == "success":
            merged = list(state.get("processed_candidate_ids", [])) + list(pending.get("candidate_ids", []))
            deduped = list(dict.fromkeys(str(x) for x in merged if str(x).strip()))
            state["processed_candidate_ids"] = deduped[-MAX_REMEMBERED_CANDIDATES:]
            actions.append({
                "type": "dce_batch_committed",
                "workflow_run_id": run.get("id"),
                "source_run": pending.get("source_run"),
                "candidates": len(pending.get("candidate_ids", [])),
            })
            state["pending_dce_batch"] = None
            return False

        # Any terminal non-success is retryable at the scheduler layer. The exact
        # downstream workflow keeps its own retry/dead-letter semantics per record.
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
        discovery = _pick_discovery(state)
        any_dce_active = fc.is_workflow_active("dce-fanout-v2.yml")

        if discovery and dce_cfg.get("enabled", True) and not pending_owns_lane and not any_dce_active:
            minimum_slots = int(dce_cfg.get("minimum_free_github_slots", 3))
            if capacity_budget >= minimum_slots:
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
                    max_parallel = max(1, min(limit, capacity_budget))
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

        disc_cfg = desired.get("discovery", {})
        last = fc.parse_ts(state.get("last_discovery_dispatch_at"))
        due = last is None or fc.NOW - last >= timedelta(minutes=int(disc_cfg.get("min_interval_minutes", 360)))
        expected_slots = int(disc_cfg.get("expected_parallel_slots", 19))
        min_slots = int(disc_cfg.get("minimum_free_github_slots", 4))
        discovery_running = fc.is_workflow_active("supergreen-discovery-v2.yml")
        backlog_pinned = bool(state.get("active_discovery_run_id"))
        allow_refresh_while_backlog = bool(disc_cfg.get("allow_refresh_while_backlog", False))
        discovery_capacity_ok = capacity_budget >= min(expected_slots, limit)

        if disc_cfg.get("enabled", True) and due and not discovery_running and (not backlog_pinned or allow_refresh_while_backlog):
            if discovery_capacity_ok or (capacity_budget >= min_slots and bool(disc_cfg.get("allow_queue_when_partially_free", False))):
                fc.dispatch("supergreen-discovery-v2.yml")
                capacity_budget = max(0, capacity_budget - min(expected_slots, limit))
                state["last_discovery_dispatch_at"] = fc.NOW.isoformat()
                actions.append({"type": "discovery_dispatch", "expected_peak_slots": expected_slots})

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
