from __future__ import annotations

import json
import re
from datetime import timedelta

import fleet_controller as fc
import fleet_controller_v3 as v3

STATE_SCHEMA_VERSION = 4
MAX_DEFERRED_DISCOVERY_RUNS = 1_000
BUNDLE_MANIFEST_ASSET = "dce-canonical-packs-manifest.json"
AGGREGATE_RECOVERY_WORKFLOW = "dce-aggregate-recovery.yml"
v3.STATE_SCHEMA_VERSION = STATE_SCHEMA_VERSION


def _dedupe(values):
    return list(dict.fromkeys(str(x) for x in values if str(x).strip()))


def _slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:120]


def _release_assets(dce_run_id: str):
    try:
        rel = fc.get_release(f"dce-harvest-{dce_run_id}")
        if not rel:
            return None, []
        asset_rows: list[dict] = []
        page = 1
        while page <= 20:
            rows = fc.api(
                f"/repos/{fc.REPO}/releases/{rel['id']}/assets?per_page=100&page={page}"
            ).json()
            if not isinstance(rows, list):
                return None, []
            if not rows:
                break
            asset_rows.extend(x for x in rows if isinstance(x, dict))
            if len(rows) < 100:
                break
            page += 1
        return rel, asset_rows
    except Exception:
        return None, []


def _bundle_manifest_ready(dce_run_id: str) -> bool:
    rel, rows = _release_assets(dce_run_id)
    if not rel:
        return False
    return any(str(x.get("name") or "") == BUNDLE_MANIFEST_ASSET for x in rows)


def _executed_candidate_ids(dce_run_id: str, leased_candidate_ids: list[str]) -> list[str] | None:
    """Resolve exact candidates backed by durable canonical execution evidence.

    Legacy DCE runs persisted one candidate-*.tar.gz Release asset per candidate.
    Single-writer runs persist a small number of bounded TAR bundles plus a manifest
    whose members retain each immutable candidate archive and sha256. Support both
    forms so controller reconciliation remains transactional across the migration.
    """
    try:
        rel, asset_rows = _release_assets(dce_run_id)
        if not rel:
            return None
        asset_names = {str(x.get("name") or "") for x in asset_rows}
        executed_slugs = {
            name[len("candidate-") : -len(".tar.gz")]
            for name in asset_names
            if name.startswith("candidate-") and name.endswith(".tar.gz")
        }

        if BUNDLE_MANIFEST_ASSET in asset_names:
            manifest_blob = fc.download_asset({**rel, "assets": asset_rows}, BUNDLE_MANIFEST_ASSET)
            if manifest_blob is None:
                return None
            manifest = json.loads(manifest_blob.decode("utf-8"))
            if manifest.get("contract") != "DCE_SINGLE_WRITER_RELEASE_BUNDLE_V1":
                return None
            for bundle in manifest.get("bundles") or []:
                for member in bundle.get("members") or []:
                    name = str(member.get("name") or "")
                    if name.startswith("candidate-") and name.endswith(".tar.gz"):
                        executed_slugs.add(name[len("candidate-") : -len(".tar.gz")])

        return [cid for cid in leased_candidate_ids if _slugify(cid) in executed_slugs]
    except Exception:
        return None


def _run_job_state(run_id: str) -> dict | None:
    """Inspect live matrix health without trusting the parent run status alone."""
    try:
        jobs: list[dict] = []
        for page in range(1, 10):
            payload = fc.api(
                f"/repos/{fc.REPO}/actions/runs/{run_id}/jobs?per_page=100&page={page}"
            ).json()
            rows = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                return None
            jobs.extend(x for x in rows if isinstance(x, dict))
            if len(rows) < 100:
                break
        shards = [j for j in jobs if str(j.get("name") or "").startswith("shard-")]
        aggregates = [j for j in jobs if str(j.get("name") or "") == "aggregate"]
        active_states = {"queued", "in_progress", "waiting", "pending", "requested"}
        active_shards = [j for j in shards if str(j.get("status") or "") in active_states]
        return {
            "total_jobs": len(jobs),
            "shards": len(shards),
            "active_shards": len(active_shards),
            "completed_success_shards": sum(
                1 for j in shards
                if str(j.get("status") or "") == "completed" and str(j.get("conclusion") or "") == "success"
            ),
            "aggregate_present": bool(aggregates),
            "aggregate_active": any(str(j.get("status") or "") in active_states for j in aggregates),
            "aggregate_success": any(
                str(j.get("status") or "") == "completed" and str(j.get("conclusion") or "") == "success"
                for j in aggregates
            ),
        }
    except Exception:
        return None


def _migrate_state(state: dict, actions: list[dict]):
    version = int(state.get("schema_version") or 0)
    state.setdefault("deferred_discovery_runs", [])
    state.setdefault("postprocessed_dce_runs", [])
    if version >= STATE_SCHEMA_VERSION:
        return

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
        ("tender-portal-yield-backfill.yml", {"dce_run_id": dce_run_id}),
    ):
        try:
            fc.dispatch(workflow, inputs)
            results.append({"workflow": workflow, "status": "DISPATCHED"})
        except Exception as exc:
            results.append({"workflow": workflow, "status": "ERROR_RETRYABLE", "error": str(exc)[:500]})

    if results and all(x["status"] == "DISPATCHED" for x in results):
        state["postprocessed_dce_runs"] = _dedupe(list(state.get("postprocessed_dce_runs", [])) + [dce_run_id])[-2_000:]
    actions.append({"type": "dce_postprocessing", "workflow_run_id": dce_run_id, "results": results})


def _commit_durable_batch(state: dict, actions: list[dict], pending: dict, leased_ids: list[str], run_id: str, executed_ids: list[str]) -> bool:
    merged = list(state.get("processed_candidate_ids", [])) + executed_ids
    state["processed_candidate_ids"] = _dedupe(merged)[-v3.MAX_REMEMBERED_CANDIDATES:]
    executed_set = set(executed_ids)
    returned = [cid for cid in leased_ids if cid not in executed_set]
    actions.append({
        "type": "dce_batch_committed",
        "workflow_run_id": run_id,
        "source_run": pending.get("source_run"),
        "leased_candidates": len(leased_ids),
        "executed_candidates": len(executed_ids),
        "returned_to_queue": len(returned),
        "execution_coverage": round(len(executed_ids) / max(1, len(leased_ids)), 6),
        "durable_transport": "single_writer_bundle" if _bundle_manifest_ready(run_id) else "legacy_individual_assets",
    })
    state["pending_dce_batch"] = None
    if run_id and executed_ids:
        _dispatch_postprocessing(run_id, actions, state)
    return False


def _reconcile_pending(state: dict, actions: list[dict]) -> bool:
    """Commit only durable executed candidates, then close DCE -> review/yield loop."""
    pending = state.get("pending_dce_batch")
    if not isinstance(pending, dict) or not pending.get("candidate_ids"):
        state["pending_dce_batch"] = None
        return False

    leased_ids = [str(x) for x in pending.get("candidate_ids", [])]
    run = v3._match_pending_run(pending)
    if run:
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        run_id = str(run.get("id") or "")

        if status in {"queued", "in_progress", "requested", "waiting", "pending"}:
            pending["workflow_run_id"] = run.get("id")

            # Stronger than the parent run state: if a single-writer manifest exists,
            # all immutable candidate packs have already been durably aggregated.
            if run_id and _bundle_manifest_ready(run_id):
                executed_ids = _executed_candidate_ids(run_id, leased_ids)
                if executed_ids is not None:
                    actions.append({
                        "type": "dce_parent_status_stale_but_durable_aggregate_ready",
                        "workflow_run_id": run_id,
                        "parent_status": status,
                        "executed_candidates": len(executed_ids),
                    })
                    return _commit_durable_batch(state, actions, pending, leased_ids, run_id, executed_ids)

            # GitHub occasionally leaves a matrix parent in_progress after every
            # shard has produced its immutable artifact and fails to materialize the
            # dependent aggregate job. Detect that exact state and self-heal once.
            health = _run_job_state(run_id) if run_id else None
            if (
                health
                and health.get("shards", 0) > 0
                and health.get("active_shards", 0) == 0
                and not health.get("aggregate_present")
                and not pending.get("aggregate_recovery_dispatched")
            ):
                try:
                    fc.dispatch(AGGREGATE_RECOVERY_WORKFLOW, {"dce_run_id": run_id})
                    pending["aggregate_recovery_dispatched"] = fc.iso(fc.NOW)
                    actions.append({
                        "type": "dce_aggregate_recovery_dispatched",
                        "workflow_run_id": run_id,
                        "job_health": health,
                    })
                except Exception as exc:
                    actions.append({
                        "type": "dce_aggregate_recovery_dispatch_error",
                        "workflow_run_id": run_id,
                        "error": str(exc)[:500],
                        "job_health": health,
                    })

            state["pending_dce_batch"] = pending
            return True

        if status == "completed" and conclusion == "success":
            executed_ids = _executed_candidate_ids(run_id, leased_ids) if run_id else None
            if executed_ids is None:
                tries = int(pending.get("durability_verification_attempts") or 0) + 1
                pending["durability_verification_attempts"] = tries
                pending["workflow_run_id"] = run.get("id")
                if tries < 4:
                    state["pending_dce_batch"] = pending
                    actions.append({
                        "type": "dce_commit_waiting_for_durable_execution_evidence",
                        "workflow_run_id": run.get("id"),
                        "leased_candidates": len(leased_ids),
                        "verification_attempt": tries,
                    })
                    return True
                actions.append({
                    "type": "dce_batch_returned_to_queue_unverified_execution",
                    "workflow_run_id": run.get("id"),
                    "source_run": pending.get("source_run"),
                    "candidates": len(leased_ids),
                })
                state["pending_dce_batch"] = None
                return False
            return _commit_durable_batch(state, actions, pending, leased_ids, run_id, executed_ids)

        actions.append({
            "type": "dce_batch_returned_to_queue",
            "workflow_run_id": run.get("id"),
            "conclusion": conclusion or "unknown",
            "source_run": pending.get("source_run"),
            "candidates": len(leased_ids),
        })
        state["pending_dce_batch"] = None
        return False

    dispatched_at = fc.parse_ts(pending.get("dispatched_at"))
    if dispatched_at and fc.NOW - dispatched_at > timedelta(minutes=15):
        actions.append({
            "type": "dce_lease_expired_returned_to_queue",
            "source_run": pending.get("source_run"),
            "candidates": len(leased_ids),
        })
        state["pending_dce_batch"] = None
        return False
    return True


v3._migrate_state = _migrate_state
v3._pick_discovery = _pick_discovery
v3._reconcile_pending = _reconcile_pending


if __name__ == "__main__":
    v3.main()
