from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from auto_select_dce import load_jsonl, select

API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPOSITORY", "walidgdg1-ai/tender-engine")
OWNER, NAME = REPO.split("/", 1)
TOKEN = os.getenv("GITHUB_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
}
NOW = datetime.now(timezone.utc)
FLEET_TAG = "fleet-state"
STATE_ASSET = "controller-state.json"
STATUS_ASSET = "fleet-status-latest.json"
GPT_ASSET = "gpt-latest-summary.json"
HISTORY_ASSET = "metrics-history.jsonl"
AUTO_QUEUE_PATH = "queues/auto_selection_latest.jsonl"
CIRCLE_TICK_PATH = "control/circleci_tick.txt"


def req(method: str, url: str, **kwargs):
    r = requests.request(method, url, headers=HEADERS, timeout=60, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub API {method} {url} -> {r.status_code}: {r.text[:1000]}")
    return r


def api(path: str, method="GET", **kwargs):
    return req(method, API + path, **kwargs)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def get_release(tag: str):
    r = requests.get(f"{API}/repos/{REPO}/releases/tags/{tag}", headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(r.text[:1000])
    return r.json()


def ensure_fleet_release():
    rel = get_release(FLEET_TAG)
    if rel:
        return rel
    payload = {
        "tag_name": FLEET_TAG,
        "target_commitish": "main",
        "name": "Tender Fleet Durable State",
        "body": "Small mutable controller/status assets only. Harvested procurement data remains in immutable per-harvest Releases.",
        "draft": False,
        "prerelease": False,
    }
    return api(f"/repos/{REPO}/releases", method="POST", json=payload).json()


def download_asset(rel: dict, name: str) -> bytes | None:
    for a in rel.get("assets", []):
        if a.get("name") == name:
            h = dict(HEADERS)
            h["Accept"] = "application/octet-stream"
            r = requests.get(a["url"], headers=h, timeout=60)
            if r.status_code >= 400:
                raise RuntimeError(f"asset download {name}: {r.status_code} {r.text[:500]}")
            return r.content
    return None


def upload_asset(rel: dict, name: str, data: bytes, content_type="application/octet-stream"):
    for a in rel.get("assets", []):
        if a.get("name") == name:
            api(f"/repos/{REPO}/releases/assets/{a['id']}", method="DELETE")
            break
    upload_url = rel["upload_url"].split("{")[0]
    h = dict(HEADERS)
    h["Content-Type"] = content_type
    r = requests.post(upload_url, headers=h, params={"name": name}, data=data, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"asset upload {name}: {r.status_code} {r.text[:500]}")
    rel.clear()
    rel.update(get_release(FLEET_TAG))


def parse_ts(v: str | None):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def workflow_runs(workflow: str, status: str | None = None, limit=20):
    q = f"?per_page={limit}"
    if status:
        q += f"&status={status}"
    r = api(f"/repos/{REPO}/actions/workflows/{workflow}/runs{q}").json()
    return r.get("workflow_runs", [])


def is_workflow_active(workflow: str):
    for status in ("in_progress", "queued"):
        if workflow_runs(workflow, status=status, limit=10):
            return True
    return False


def latest_usable_discovery():
    # Correctness is based on durable data, not merely the workflow badge. A source
    # validation job may fail after the consolidated pack has already been safely written.
    for run in workflow_runs("supergreen-discovery-v2.yml", status="completed", limit=30):
        rid = str(run.get("id") or "")
        if not rid:
            continue
        rel = get_release(f"discovery-harvest-{rid}")
        if not rel:
            continue
        names = {a.get("name") for a in rel.get("assets", [])}
        if f"supergreen-wide-read-{rid}-repaired.tar.gz" in names or f"supergreen-wide-read-{rid}.tar.gz" in names:
            return run
    return None


def public_fleet_jobs():
    patterns = re.compile(r"(tender|harvest|lead|rental|airbnb|gws|procure)", re.I)
    repos = api(f"/users/{OWNER}/repos?per_page=100&type=owner&sort=updated").json()
    targets = [x for x in repos if not x.get("private") and (x.get("name") == NAME or patterns.search(x.get("name", "")))]
    active_jobs = queued_jobs = 0
    detail = []
    for repo in targets[:30]:
        full = repo["full_name"]
        aruns = []
        try:
            for status in ("in_progress", "queued"):
                rr = api(f"/repos/{full}/actions/runs?status={status}&per_page=30").json().get("workflow_runs", [])
                aruns.extend(rr)
            r_active = r_queued = 0
            for run in aruns:
                jobs = api(f"/repos/{full}/actions/runs/{run['id']}/jobs?per_page=100").json().get("jobs", [])
                if jobs:
                    r_active += sum(1 for j in jobs if j.get("status") == "in_progress")
                    r_queued += sum(1 for j in jobs if j.get("status") == "queued")
                elif run.get("status") == "queued":
                    r_queued += 1
            active_jobs += r_active
            queued_jobs += r_queued
            if r_active or r_queued:
                detail.append({"repo": full, "active_jobs": r_active, "queued_jobs": r_queued})
        except Exception as exc:
            detail.append({"repo": full, "visibility": "public", "capacity_read": "unavailable", "error": str(exc)[:300]})
    return active_jobs, queued_jobs, detail


def circleci_commit_status():
    try:
        ref = api(f"/repos/{REPO}/git/ref/heads/circleci-fleet").json()
        sha = ref.get("object", {}).get("sha")
        if not sha:
            return {"state": "unknown"}
        data = api(f"/repos/{REPO}/commits/{sha}/status").json()
        matches = [s for s in data.get("statuses", []) if "circleci" in str(s.get("context", "")).lower()]
        if not matches:
            return {"state": "no_status", "sha": sha}
        return {
            "state": matches[0].get("state"),
            "context": matches[0].get("context"),
            "sha": sha,
            "target_url": matches[0].get("target_url"),
        }
    except Exception as exc:
        return {"state": "unavailable", "error": str(exc)[:300]}


def dispatch(workflow: str, inputs: dict[str, str] | None = None):
    payload: dict[str, Any] = {"ref": "main"}
    if inputs:
        payload["inputs"] = {k: str(v) for k, v in inputs.items()}
    r = requests.post(f"{API}/repos/{REPO}/actions/workflows/{workflow}/dispatches", headers=HEADERS, json=payload, timeout=30)
    if r.status_code not in (204, 201):
        raise RuntimeError(f"dispatch {workflow}: {r.status_code} {r.text[:1000]}")


def get_file(path: str):
    r = requests.get(f"{API}/repos/{REPO}/contents/{path}?ref=main", headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(r.text[:1000])
    return r.json()


def update_repo_text(path: str, text: str, message: str):
    current = get_file(path)
    payload = {"message": message, "content": base64.b64encode(text.encode()).decode(), "branch": "main"}
    if current:
        payload["sha"] = current["sha"]
    for _ in range(3):
        r = requests.put(f"{API}/repos/{REPO}/contents/{path}", headers=HEADERS, json=payload, timeout=30)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 409:
            current = get_file(path)
            if current:
                payload["sha"] = current["sha"]
            continue
        raise RuntimeError(f"update {path}: {r.status_code} {r.text[:1000]}")
    raise RuntimeError(f"update {path}: repeated conflict")


def select_from_discovery(run_id: str, minimum: int, limit: int, processed: set[str]):
    tag = f"discovery-harvest-{run_id}"
    asset = f"supergreen-wide-read-{run_id}.tar.gz"
    rel = get_release(tag)
    if not rel:
        return [], {"error": f"missing release {tag}"}
    names = {a.get("name") for a in rel.get("assets", [])}
    repaired = f"supergreen-wide-read-{run_id}-repaired.tar.gz"
    if repaired in names:
        asset = repaired
    blob = download_asset(rel, asset)
    if blob is None:
        return [], {"error": f"missing {asset}"}
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            tf.extractall(td, filter="data")
        found = list(Path(td).rglob("current_candidates.jsonl"))
        if not found:
            return [], {"error": "current_candidates.jsonl absent"}
        rows = list(load_jsonl(found[0]))
    for r in rows:
        r["wide_read_run_id"] = run_id
    selected = select(rows, minimum=minimum, limit=limit, blocked_ids=processed)
    return selected, {"input": len(rows), "selected": len(selected), "source_release": tag, "asset": asset}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desired", default="control/desired_state.json")
    ap.add_argument("--providers", default="control/provider_limits.json")
    args = ap.parse_args()
    desired = load_json(Path(args.desired), {})
    providers = load_json(Path(args.providers), {})
    rel = ensure_fleet_release()
    state_raw = download_asset(rel, STATE_ASSET)
    state = json.loads(state_raw.decode()) if state_raw else {}
    state.setdefault("processed_discovery_runs", [])
    state.setdefault("processed_candidate_ids", [])
    state.setdefault("last_discovery_dispatch_at", None)
    state.setdefault("last_circleci_tick_at", None)

    enabled = bool(desired.get("enabled")) and bool(desired.get("continuous"))
    limit = int(os.getenv("GITHUB_CONCURRENCY_LIMIT") or providers.get("providers", {}).get("github", {}).get("standard_hosted_concurrency_limit", 20))
    active, queued, fleet_detail = public_fleet_jobs()
    effective_active_after_controller = max(0, active - 1)
    available_after_controller = max(0, limit - effective_active_after_controller)
    capacity_budget = available_after_controller

    actions = []
    errors = []
    selection_stats = None

    if enabled:
        # 1) Use spare capacity for deterministic DCE prefetch. If discovery is still
        # running, this naturally work-steals only the slots it has not occupied.
        latest = latest_usable_discovery()
        processed_runs = set(str(x) for x in state.get("processed_discovery_runs", []))
        dce_cfg = desired.get("dce", {})
        if latest and dce_cfg.get("enabled", True) and str(latest["id"]) not in processed_runs and not is_workflow_active("dce-fanout-v2.yml"):
            if capacity_budget >= int(dce_cfg.get("minimum_free_github_slots", 3)):
                selected, selection_stats = select_from_discovery(
                    str(latest["id"]),
                    int(dce_cfg.get("minimum_retrieval_priority", 34)),
                    int(dce_cfg.get("max_candidates_per_cycle", 320)),
                    set(state.get("processed_candidate_ids", [])),
                )
                if selected:
                    text = "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in selected)
                    update_repo_text(AUTO_QUEUE_PATH, text, f"Autonomous DCE queue from discovery {latest['id']}")
                    max_parallel = max(1, min(limit, capacity_budget))
                    dispatch("dce-fanout-v2.yml", {
                        "selection_path": AUTO_QUEUE_PATH,
                        "source_discovery_run": str(latest["id"]),
                        "max_jobs": str(len(selected)),
                        "max_parallel": str(max_parallel),
                        "max_shards": "256",
                        "jobs_per_shard": "2",
                    })
                    capacity_budget = max(0, capacity_budget - max_parallel)
                    state["processed_candidate_ids"] = (state.get("processed_candidate_ids", []) + [x["candidate_id"] for x in selected])[-10000:]
                    actions.append({"type": "dce_dispatch", "source_run": latest["id"], "candidates": len(selected), "max_parallel": max_parallel})
                state["processed_discovery_runs"] = (state.get("processed_discovery_runs", []) + [str(latest["id"])])[-500:]

        # 2) Discovery now has 1 TED + 8 Contracts Finder + 10 Ireland jobs at peak.
        # Do not deliberately enqueue it behind a full DCE fanout; use idle slots later.
        disc = desired.get("discovery", {})
        last = parse_ts(state.get("last_discovery_dispatch_at"))
        due = last is None or NOW - last >= timedelta(minutes=int(disc.get("min_interval_minutes", 45)))
        expected_slots = int(disc.get("expected_parallel_slots", 19))
        min_slots = int(disc.get("minimum_free_github_slots", 4))
        discovery_capacity_ok = capacity_budget >= min(expected_slots, limit)
        if disc.get("enabled", True) and due and not is_workflow_active("supergreen-discovery-v2.yml"):
            if discovery_capacity_ok or (capacity_budget >= min_slots and bool(disc.get("allow_queue_when_partially_free", False))):
                dispatch("supergreen-discovery-v2.yml")
                capacity_budget = max(0, capacity_budget - min(expected_slots, limit))
                state["last_discovery_dispatch_at"] = NOW.isoformat()
                actions.append({"type": "discovery_dispatch", "expected_peak_slots": expected_slots})

        # 3) CircleCI is a separate capacity pool, but heavy fanout only happens on the
        # isolated branch and only if its durable GitHub write bridge is present.
        cc = desired.get("circleci", {})
        last_cc = parse_ts(state.get("last_circleci_tick_at"))
        cc_due = last_cc is None or NOW - last_cc >= timedelta(minutes=int(cc.get("refresh_interval_minutes", 1440)))
        if cc.get("desired_enabled") and cc_due:
            tick = f"tick={NOW.isoformat()}\nreason=autonomous-refresh\n"
            update_repo_text(cc.get("trigger_file", CIRCLE_TICK_PATH), tick, f"Trigger CircleCI autonomous refresh {NOW.isoformat()}")
            state["last_circleci_tick_at"] = NOW.isoformat()
            actions.append({"type": "circleci_tick", "max_parallel": int(cc.get("max_parallel", 30))})

    state["updated_at"] = NOW.isoformat()
    state["enabled"] = enabled
    state["mode"] = desired.get("mode", "maximum")
    circle_status = circleci_commit_status()

    status = {
        "generated_at": NOW.isoformat(),
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
        "generated_at": NOW.isoformat(),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "harvest_continues_without_gpt": enabled,
        "actions": actions,
        "github_active_jobs": active,
        "github_queued_jobs": queued,
        "circleci_status": circle_status,
        "latest_discovery_processed": state.get("processed_discovery_runs", [])[-1:] or [],
        "gpt_role": "review only ambiguous/high-value/final mandatory-gate evidence; deterministic discovery/DCE prefetch continues autonomously",
    }

    old_hist = download_asset(rel, HISTORY_ASSET)
    hist = old_hist.decode("utf-8", errors="replace").splitlines() if old_hist else []
    hist.append(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    hist = hist[-500:]

    upload_asset(rel, STATE_ASSET, json.dumps(state, indent=2).encode(), "application/json")
    upload_asset(rel, STATUS_ASSET, json.dumps(status, indent=2).encode(), "application/json")
    upload_asset(rel, GPT_ASSET, json.dumps(gpt, indent=2).encode(), "application/json")
    upload_asset(rel, HISTORY_ASSET, ("\n".join(hist) + "\n").encode(), "application/x-ndjson")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
