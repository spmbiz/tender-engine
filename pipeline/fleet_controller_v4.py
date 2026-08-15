from __future__ import annotations

from datetime import timedelta

import fleet_controller as fc
import fleet_controller_v3 as v3

STATE_SCHEMA_VERSION = 4
MAX_DEFERRED_DISCOVERY_RUNS = 1_000
v3.STATE_SCHEMA_VERSION = STATE_SCHEMA_VERSION


def _dedupe(values):
    return list(dict.fromkeys(str(x) for x in values if str(x).strip()))


def _migrate_state(state: dict, actions: list[dict]):
    version = int(state.get("schema_version") or 0)
    state.setdefault("deferred_discovery_runs", [])
    state.setdefault("postprocessed_dce_runs", [])
    if version >= STATE_SCHEMA_VERSION:
        return

    # v1/v2 treated dispatched rows as completed. Preserve the old safety migration
    # only for those schemas. v3 -> v4 MUST preserve durable processed IDs and any
    # live DCE lease.
    if version < 3:
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
    actions.append({
        "type": "state_migration",
        "from_schema": version,
        "to_schema": STATE_SCHEMA_VERSION,
        "processed_candidate_ids_preserved": len(state.get("processed_candidate_ids", [])),
        "pending_dce_candidates_preserved": len((state.get("pending_dce_batch") or {}).get("candidate_ids", [])),
    })


def _pick_discovery(state: dict):
    """Prefer the freshest durable usable harvest while preserving older backlog."""
    completed = {str(x) for x in state.get("processed_discovery_runs", [])}
    active_id = str(state.get("active_discovery_run_id") or "").strip()
    deferred = [x for x in _dedupe(state.get("deferred_discovery_runs", [])) if x not in completed]

    latest = fc.latest_usable_discovery()
    latest_id = str((latest or {}).get("id") or "").strip()

    # Freshness preemption: a newer usable release wins immediately. The previous
    # active harvest is deferred, never discarded, and resumes after the fresh one drains.
    if latest_id and latest_id not in completed and latest_id != active_id:
        if active_id and active_id not in completed and v3._usable_discovery(active_id):
            deferred.append(active_id)
        deferred = [x for x in _dedupe(deferred) if x != latest_id and x not in completed]
        state["deferred_discovery_runs"] = deferred[-MAX_DEFERRED_DISCOVERY_RUNS:]
        state["active_discovery_run_id"] = latest_id
        return latest

    if active_id and active_id not in completed:
        active = v3._usable_discovery(active_id)
        if active:
            state["deferred_discovery_runs"] = deferred[-MAX_DEFERRED_DISCOVERY_RUNS:]
            return active
        state["active_discovery_run_id"] = None

    # Resume deferred backlog newest-first once the freshest harvest is drained.
    for rid in reversed(deferred):
        if rid in completed:
            continue
        usable = v3._usable_discovery(rid)
        if usable:
            state["deferred_discovery_runs"] = [x for x in deferred if x != rid][-MAX_DEFERRED_DISCOVERY_RUNS:]
            state["active_discovery_run_id"] = rid
            return usable

    if latest_id and latest_id not in completed:
        state["active_discovery_run_id"] = latest_id
        return latest

    state["deferred_discovery_runs"] = deferred[-MAX_DEFERRED_DISCOVERY_RUNS:]
    state["active_discovery_run_id"] = None
    return None


def _dispatch_postprocessing(dce_run_id: str, actions: list[dict], state: dict):
    already = {str(x) for x in state.get("postprocessed_dce_runs", [])}
    if dce_run_id in already:
        return

    results = []
    for workflow, inputs in (
        ("dce-gpt-handoff.yml", {"dce_run_id": dce_run_id}),
        ("auto-dce-adjudication.yml", {"dce_run_id": dce_run_id}),
    ):
        try:
            fc.dispatch(workflow, inputs)
            results.append({"workflow": workflow, "status": "DISPATCHED"})
        except Exception as exc:
            # Never lose a successfully retrieved DCE batch because a downstream
            # review transport could not start. The next controller tick can retry.
            results.append({"workflow": workflow, "status": "ERROR_RETRYABLE", "error": str(exc)[:500]})

    if results and all(x["status"] == "DISPATCHED" for x in results):
        state["postprocessed_dce_runs"] = _dedupe(list(state.get("postprocessed_dce_runs", [])) + [dce_run_id])[-2_000:]
    actions.append({"type": "dce_postprocessing", "workflow_run_id": dce_run_id, "results": results})


def _reconcile_pending(state: dict, actions: list[dict]) -> bool:
    """Commit a successful lease, then immediately close the DCE -> review loop."""
    pending = state.get("pending_dce_batch")
    if not isinstance(pending, dict) or not pending.get("candidate_ids"):
        state["pending_dce_batch"] = None
        return False

    run = v3._match_pending_run(pending)
    if run:
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        if status in {"queued", "in_progress", "requested", "waiting", "pending"}:
            pending["workflow_run_id"] = run.get("id")
            state["pending_dce_batch"] = pending
            return True

        if status == "completed" and conclusion == "success":
            merged = list(state.get("processed_candidate_ids", [])) + list(pending.get("candidate_ids", []))
            state["processed_candidate_ids"] = _dedupe(merged)[-v3.MAX_REMEMBERED_CANDIDATES:]
            run_id = str(run.get("id") or "")
            actions.append({
                "type": "dce_batch_committed",
                "workflow_run_id": run.get("id"),
                "source_run": pending.get("source_run"),
                "candidates": len(pending.get("candidate_ids", [])),
            })
            state["pending_dce_batch"] = None
            if run_id:
                _dispatch_postprocessing(run_id, actions, state)
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


v3._migrate_state = _migrate_state
v3._pick_discovery = _pick_discovery
v3._reconcile_pending = _reconcile_pending


if __name__ == "__main__":
    v3.main()
