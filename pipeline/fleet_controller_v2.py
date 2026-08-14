from __future__ import annotations

import argparse
import json
import os
from datetime import timedelta
from pathlib import Path

import fleet_controller as fc


MAX_REMEMBERED_CANDIDATES = 100_000
MAX_REMEMBERED_DISCOVERY_RUNS = 1_000


def _usable_discovery(run_id: str):
    rel = fc.get_release(f"discovery-harvest-{run_id}")
    if not rel:
        return None
    names = {a.get("name") for a in rel.get("assets", [])}
    if f"supergreen-wide-read-{run_id}-repaired.tar.gz" in names or f"supergreen-wide-read-{run_id}.tar.gz" in names:
        return {"id": str(run_id)}
    return None


def _pick_discovery(state: dict):
    processed = {str(x) for x in state.get("processed_discovery_runs", [])}
    active_id = str(state.get("active_discovery_run_id") or "").strip()
    if active_id and active_id not in processed:
        active = _usable_discovery(active_id)
        if active:
            return active
        # Do not pin the fleet forever to an asset that no longer exists.
        state["active_discovery_run_id"] = None

    latest = fc.latest_usable_discovery()
    if latest and str(latest.get("id")) not in processed:
        state["active_discovery_run_id"] = str(latest["id"])
        return latest
    return None


def _emit_output(name: str, value: str):
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


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
    state.setdefault("last_discovery_dispatch_at", None)
    state.setdefault("last_circleci_tick_at", None)

    enabled = bool(desired.get("enabled")) and bool(desired.get("continuous"))
    github_cfg = providers.get("providers", {}).get("github", {})
    limit = int(os.getenv("GITHUB_CONCURRENCY_LIMIT") or github_cfg.get("standard_hosted_concurrency_limit", 20))

    active, queued, fleet_detail = fc.public_fleet_jobs()
    # This controller consumes one observed active slot and exits before dispatched
    # fanout reaches peak, so return its own slot to the planning budget.
    effective_active_after_controller = max(0, active - 1)
    available_after_controller = max(0, limit - effective_active_after_controller)
    capacity_budget = available_after_controller

    actions = []
    errors = []
    selection_stats = None
    circle_tick_sha = ""

    if enabled:
        dce_cfg = desired.get("dce", {})
        discovery = _pick_discovery(state)
        dce_active = fc.is_workflow_active("dce-fanout-v2.yml")

        # Drain one immutable discovery harvest repeatedly. A 14k-record harvest is
        # NOT considered consumed after the first 320 records. Every controller cycle
        # excludes durable previously-dispatched candidate IDs, takes the next useful
        # batch, and only marks the harvest drained when no qualifying net-new records
        # remain. This is the durable backlog/lease equivalent for discovery -> DCE.
        if discovery and dce_cfg.get("enabled", True) and not dce_active:
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
                    queue_text = "".join(
                        json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n"
                        for x in selected
                    )
                    fc.update_repo_text(
                        fc.AUTO_QUEUE_PATH,
                        queue_text,
                        f"Autonomous DCE queue from discovery {run_id}",
                    )
                    max_parallel = max(1, min(limit, capacity_budget))
                    fc.dispatch(
                        "dce-fanout-v2.yml",
                        {
                            "selection_path": fc.AUTO_QUEUE_PATH,
                            "source_discovery_run": run_id,
                            "max_jobs": str(len(selected)),
                            "max_parallel": str(max_parallel),
                            "max_shards": "256",
                            "jobs_per_shard": "2",
                        },
                    )
                    capacity_budget = max(0, capacity_budget - max_parallel)
                    remembered = state.get("processed_candidate_ids", []) + [x["candidate_id"] for x in selected]
                    state["processed_candidate_ids"] = remembered[-MAX_REMEMBERED_CANDIDATES:]
                    state["active_discovery_run_id"] = run_id
                    actions.append(
                        {
                            "type": "dce_dispatch",
                            "source_run": run_id,
                            "candidates": len(selected),
                            "max_parallel": max_parallel,
                            "harvest_drained": False,
                        }
                    )
                else:
                    completed = state.get("processed_discovery_runs", []) + [run_id]
                    state["processed_discovery_runs"] = completed[-MAX_REMEMBERED_DISCOVERY_RUNS:]
                    state["active_discovery_run_id"] = None
                    actions.append(
                        {
                            "type": "discovery_backlog_drained",
                            "source_run": run_id,
                            "minimum_retrieval_priority": int(dce_cfg.get("minimum_retrieval_priority", 34)),
                        }
                    )

        # Deep refresh is deliberately slower than the five-minute controller wakeup:
        # work is continuously drained every wakeup, while expensive full source scans
        # do not waste compute rediscovering the same 365-day universe every few minutes.
        disc_cfg = desired.get("discovery", {})
        last = fc.parse_ts(state.get("last_discovery_dispatch_at"))
        due = last is None or fc.NOW - last >= timedelta(minutes=int(disc_cfg.get("min_interval_minutes", 360)))
        expected_slots = int(disc_cfg.get("expected_parallel_slots", 19))
        min_slots = int(disc_cfg.get("minimum_free_github_slots", 4))
        discovery_running = fc.is_workflow_active("supergreen-discovery-v2.yml")
        backlog_pinned = bool(state.get("active_discovery_run_id"))
        allow_refresh_while_backlog = bool(disc_cfg.get("allow_refresh_while_backlog", False))
        discovery_capacity_ok = capacity_budget >= min(expected_slots, limit)

        if (
            disc_cfg.get("enabled", True)
            and due
            and not discovery_running
            and (not backlog_pinned or allow_refresh_while_backlog)
        ):
            if discovery_capacity_ok or (
                capacity_budget >= min_slots
                and bool(disc_cfg.get("allow_queue_when_partially_free", False))
            ):
                fc.dispatch("supergreen-discovery-v2.yml")
                capacity_budget = max(0, capacity_budget - min(expected_slots, limit))
                state["last_discovery_dispatch_at"] = fc.NOW.isoformat()
                actions.append(
                    {
                        "type": "discovery_dispatch",
                        "expected_peak_slots": expected_slots,
                    }
                )

        # CircleCI is a second compute pool. Trigger it only on its own cadence; the
        # workflow moves the exact commit SHA returned here to circleci-fleet so a
        # concurrent main-branch writer cannot race away the intended trigger.
        cc = desired.get("circleci", {})
        last_cc = fc.parse_ts(state.get("last_circleci_tick_at"))
        cc_due = last_cc is None or fc.NOW - last_cc >= timedelta(
            minutes=int(cc.get("refresh_interval_minutes", 1440))
        )
        if cc.get("desired_enabled") and cc_due:
            tick = f"tick={fc.NOW.isoformat()}\nreason=autonomous-refresh\n"
            result = fc.update_repo_text(
                cc.get("trigger_file", fc.CIRCLE_TICK_PATH),
                tick,
                f"Trigger CircleCI autonomous refresh {fc.NOW.isoformat()}",
            )
            circle_tick_sha = str((result.get("commit") or {}).get("sha") or "")
            state["last_circleci_tick_at"] = fc.NOW.isoformat()
            actions.append(
                {
                    "type": "circleci_tick",
                    "max_parallel": int(cc.get("max_parallel", 30)),
                    "commit_sha": circle_tick_sha or None,
                }
            )

    state["updated_at"] = fc.NOW.isoformat()
    state["enabled"] = enabled
    state["mode"] = desired.get("mode", "maximum")
    circle_status = fc.circleci_commit_status()

    status = {
        "generated_at": fc.NOW.isoformat(),
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
            "remembered_candidate_ids": len(state.get("processed_candidate_ids", [])),
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
        "circleci_status": circle_status,
        "latest_discovery_processed": state.get("processed_discovery_runs", [])[-1:] or [],
        "gpt_role": "review only ambiguous/high-value/final mandatory-gate evidence; deterministic discovery and DCE prefetch continue autonomously",
    }

    old_hist = fc.download_asset(fleet_release, fc.HISTORY_ASSET)
    history = old_hist.decode("utf-8", errors="replace").splitlines() if old_hist else []
    history.append(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    history = history[-500:]

    fc.upload_asset(fleet_release, fc.STATE_ASSET, json.dumps(state, indent=2).encode(), "application/json")
    fc.upload_asset(fleet_release, fc.STATUS_ASSET, json.dumps(status, indent=2).encode(), "application/json")
    fc.upload_asset(fleet_release, fc.GPT_ASSET, json.dumps(gpt, indent=2).encode(), "application/json")
    fc.upload_asset(
        fleet_release,
        fc.HISTORY_ASSET,
        ("\n".join(history) + "\n").encode(),
        "application/x-ndjson",
    )

    _emit_output("circleci_tick_sha", circle_tick_sha)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
