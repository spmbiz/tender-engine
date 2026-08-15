from __future__ import annotations

"""Broker-, yield- and historical-prior-aware Tender controller wrapper.

Historical Market Brain priors are strictly a bounded pre-DCE retrieval signal.
They cannot satisfy eligibility, DCE authority, or final verdict gates.
"""

import json
from datetime import datetime, timedelta, timezone

import requests

import auto_select_dce as selector_mod
import dce_orphan_reconcile
import fleet_controller as fc
import historical_market_priors as historical_priors
from github_api_resilience import install as install_github_resilience

install_github_resilience(fc)

EVERGREEN_REPO = "walidgdg1-ai/evergreenleadminer"
BROKER_TAG = "global-fleet-broker"
BROKER_ASSET = "global-capacity.json"
PORTAL_PERFORMANCE_ASSET = "portal-performance.json"
DEFAULT_MINIMUMS = {"hospitality": 6, "gws": 3}
DISCOVERY_WORKFLOW = "supergreen-discovery-v2.yml"
ORPHAN_RECONCILE_INTERVAL_MINUTES = 30

_HISTORICAL_PRIORS = historical_priors.load()
_ORIGINAL_RETRIEVAL_SCORE = selector_mod.retrieval_score


def _retrieval_score_with_historical_prior(rec: dict, portal_performance: dict | None = None):
    score, reasons = _ORIGINAL_RETRIEVAL_SCORE(rec, portal_performance=portal_performance)
    delta, hist_reasons = historical_priors.adjustment(rec, _HISTORICAL_PRIORS)
    if delta:
        score = max(-100, min(100, score + delta))
        reasons = list(reasons) + hist_reasons
    return score, reasons


selector_mod.retrieval_score = _retrieval_score_with_historical_prior


def _release_asset_json(repo: str, tag: str, name: str):
    try:
        rel = requests.get(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "tender-fleet-broker/1.1"},
            timeout=20,
        )
        if rel.status_code != 200:
            return None
        asset = next((a for a in rel.json().get("assets") or [] if a.get("name") == name), None)
        if not asset:
            return None
        r = requests.get(
            asset["url"],
            headers={"Accept": "application/octet-stream", "User-Agent": "tender-fleet-broker/1.1"},
            timeout=20,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _policy():
    try:
        r = requests.get(
            f"https://raw.githubusercontent.com/{EVERGREEN_REPO}/main/config/global_fleet.json",
            headers={"User-Agent": "tender-fleet-broker/1.1"},
            timeout=20,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _sibling_missing_headroom(fleet_detail: list[dict]) -> tuple[int, dict]:
    policy = _policy()
    workloads = policy.get("workloads") or {}
    state = _release_asset_json(EVERGREEN_REPO, BROKER_TAG, BROKER_ASSET) or {}
    demand = ((state.get("last_decision") or {}).get("demand") or {})
    if not demand:
        demand = {"hospitality": 1, "gws": 0}
    active_evergreen = sum(
        int(x.get("active_jobs") or 0)
        for x in fleet_detail
        if str(x.get("repo") or "") == EVERGREEN_REPO
    )
    target = 0
    components = {}
    for name in ("hospitality", "gws"):
        cfg = workloads.get(name) or {}
        enabled = bool(cfg.get("enabled", True))
        backlog = int(demand.get(name, 0) or 0)
        floor = int(cfg.get("min_slots_when_demanding") or DEFAULT_MINIMUMS[name])
        need = min(backlog, floor) if enabled and backlog > 0 else 0
        components[name] = {"demand": backlog, "minimum": floor, "target": need}
        target += need
    missing = max(0, target - active_evergreen)
    return missing, {
        "at": datetime.now(timezone.utc).isoformat(),
        "active_evergreen_jobs": active_evergreen,
        "guaranteed_target": target,
        "missing_virtual_headroom": missing,
        "components": components,
        "broker_state_updated_at": state.get("updated_at"),
    }


_original_public_fleet_jobs = fc.public_fleet_jobs
_original_select = fc.select
_original_dispatch = fc.dispatch


def _broker_aware_public_fleet_jobs():
    active, queued, detail = _original_public_fleet_jobs()
    missing, decision = _sibling_missing_headroom(detail)
    if missing:
        detail = list(detail) + [{
            "repo": "virtual://global-capacity-broker",
            "active_jobs": missing,
            "queued_jobs": 0,
            "reason": "guaranteed sibling headroom not yet satisfied by live jobs",
            "decision": decision,
        }]
    print(json.dumps({"global_capacity_guard": decision}, separators=(",", ":")))
    return active + missing, queued, detail


def _yield_aware_select(records, minimum=34, limit=320, blocked_ids=None, **kwargs):
    performance = _release_asset_json(fc.REPO, fc.FLEET_TAG, PORTAL_PERFORMANCE_ASSET) or {}
    print(json.dumps({
        "portal_yield_scheduler": {
            "history_run_ids": performance.get("run_ids") or [],
            "observed_portals": len((performance.get("portals") or {})),
            "exploit_explore": "85/15",
            "historical_market_brain": "READY" if _HISTORICAL_PRIORS else "INACTIVE",
        }
    }, separators=(",", ":")))
    return _original_select(
        records, minimum=minimum, limit=limit, blocked_ids=blocked_ids,
        portal_performance=performance,
    )


def _delta_aware_dispatch(workflow: str, inputs: dict | None = None):
    if workflow == DISCOVERY_WORKFLOW:
        merged = dict(inputs or {})
        merged.setdefault("mode", "delta")
        print(json.dumps({"discovery_dispatch": {"workflow": workflow, "mode": merged["mode"]}}, separators=(",", ":")))
        return _original_dispatch(workflow, merged)
    return _original_dispatch(workflow, inputs)


fc.public_fleet_jobs = _broker_aware_public_fleet_jobs
fc.select = _yield_aware_select
fc.dispatch = _delta_aware_dispatch

import fleet_controller_v4 as v4  # noqa: E402,F401
import fleet_controller_v3 as v3  # noqa: E402

_original_reconcile_pending = v3._reconcile_pending


def _release_successful_zero_shard_lease(state: dict, actions: list[dict]) -> bool:
    pending = state.get("pending_dce_batch")
    if not isinstance(pending, dict) or not pending.get("candidate_ids"):
        return False
    run = v3._match_pending_run(pending)
    if not run:
        return False
    if str(run.get("status") or "") != "completed" or str(run.get("conclusion") or "") != "success":
        return False
    run_id = str(run.get("id") or "")
    health = v4._run_job_state(run_id) if run_id else None
    if not health or int(health.get("shards") or 0) != 0:
        return False
    leased = [str(x) for x in pending.get("candidate_ids") or []]
    actions.append({
        "type": "dce_zero_shard_lease_released_immediately",
        "workflow_run_id": run_id,
        "source_run": pending.get("source_run"),
        "leased_candidates": len(leased),
        "job_health": health,
        "reason": "prepare-only successful run executed zero DCE shards; all leased candidates returned to durable queue",
    })
    state["pending_dce_batch"] = None
    return True


def _reconcile_pending_with_orphans(state: dict, actions: list[dict]) -> bool:
    # A successful prepare-only DCE run is an admission defer, not execution.
    # Release its entire lease immediately so the next controller cycle can
    # redispatch as soon as runner capacity is available.
    if _release_successful_zero_shard_lease(state, actions):
        return False

    last = fc.parse_ts(state.get("last_orphan_reconcile_at"))
    due = last is None or fc.NOW - last >= timedelta(minutes=ORPHAN_RECONCILE_INTERVAL_MINUTES)
    if due:
        dce_orphan_reconcile.reconcile(fc, state, actions, recent_limit=20)
        state["last_orphan_reconcile_at"] = fc.NOW.isoformat()
    else:
        actions.append({
            "type": "dce_orphan_reconcile_skipped_not_due",
            "last_at": state.get("last_orphan_reconcile_at"),
            "interval_minutes": ORPHAN_RECONCILE_INTERVAL_MINUTES,
        })
    return _original_reconcile_pending(state, actions)


v3._reconcile_pending = _reconcile_pending_with_orphans


if __name__ == "__main__":
    v3.main()
