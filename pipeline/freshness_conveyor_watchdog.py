#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPOSITORY", "walidgdg1-ai/tender-engine")
TOKEN = os.getenv("GITHUB_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "tender-freshness-watchdog/1.1",
    **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
}

DISCOVERY_WORKFLOW = "supergreen-discovery-v2.yml"
SNAPSHOT_WORKFLOW = "live-world-snapshot.yml"
LEDGER_WORKFLOW = "notice-intelligence-ledger.yml"
QWEN_CONTROLLER_WORKFLOW = "qwen-backlog-watchdog.yml"
ACTIVE_RUN_STATES = {"in_progress", "queued", "waiting", "pending", "requested"}
MAX_ACTIVE_AGE_BY_WORKFLOW = {
    SNAPSHOT_WORKFLOW: 60,
    LEDGER_WORKFLOW: 45,
}
DEFAULT_MAX_ACTIVE_AGE_MINUTES = 90


@dataclass(frozen=True)
class StageState:
    discovery: str | None
    snapshot: str | None
    ledger: str | None
    qwen: str | None
    qwen_remaining: int | None = None


def request(method: str, path: str, **kwargs) -> requests.Response:
    r = requests.request(method, f"{API}{path}", headers=HEADERS, timeout=45, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub API {method} {path} -> {r.status_code}: {r.text[:800]}")
    return r


def api_json(path: str) -> Any:
    return request("GET", path).json()


def release(tag: str) -> dict[str, Any] | None:
    r = requests.get(f"{API}/repos/{REPO}/releases/tags/{tag}", headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"release {tag}: {r.status_code} {r.text[:500]}")
    data = r.json()
    return data if isinstance(data, dict) else None


def release_asset_json(tag: str, name: str) -> dict[str, Any] | None:
    rel = release(tag)
    if not rel:
        return None
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == name), None)
    if not asset:
        return None
    h = dict(HEADERS)
    h["Accept"] = "application/octet-stream"
    r = requests.get(asset["url"], headers=h, timeout=45)
    if r.status_code >= 400:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def latest_usable_discovery() -> str | None:
    runs = api_json(f"/repos/{REPO}/actions/workflows/{DISCOVERY_WORKFLOW}/runs?status=completed&per_page=30")
    for run in runs.get("workflow_runs") or []:
        rid = str(run.get("id") or "").strip()
        if not rid:
            continue
        rel = release(f"discovery-harvest-{rid}")
        if not rel:
            continue
        names = {str(a.get("name") or "") for a in rel.get("assets") or []}
        if f"supergreen-wide-read-{rid}-repaired.tar.gz" in names or f"supergreen-wide-read-{rid}.tar.gz" in names:
            return rid
    return None


def parse_run_id(text: str | None, *patterns: str) -> str | None:
    raw = str(text or "")
    for pattern in patterns:
        m = re.search(pattern, raw, flags=re.I)
        if m:
            return m.group(1)
    return None


def parse_int(text: str | None, pattern: str) -> int | None:
    m = re.search(pattern, str(text or ""), flags=re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_ts(value: object):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def snapshot_source_run() -> str | None:
    manifest = release_asset_json("live-world-snapshot-latest", "snapshot-manifest-latest.json")
    if manifest:
        value = manifest.get("source_discovery_run")
        if value is not None:
            return str(value)
    rel = release("live-world-snapshot-latest") or {}
    return parse_run_id(
        f"{rel.get('name', '')} {rel.get('body', '')}",
        r"current\s+canonical\s+discovery\s+run\s*[:=]\s*(\d+)",
        r"source[_ -]?run\s*[:=]\s*(\d+)",
        r"LATEST\s*\((\d+)\)",
    )


def ledger_source_run() -> str | None:
    rel = release("notice-intelligence-ledger-latest") or {}
    return parse_run_id(
        f"{rel.get('name', '')} {rel.get('body', '')}",
        r"\brun\s*=\s*(\d+)",
        r"LATEST\s*\((\d+)\)",
    )


def qwen_release_state() -> tuple[str | None, int | None]:
    rel = release("qwen-classification-state-latest") or {}
    raw = f"{rel.get('name', '')} {rel.get('body', '')}"
    source = parse_run_id(
        raw,
        r"source[_ -]?run\s*=\s*(\d+)",
        r"LATEST\s*\((\d+)(?:/|\))",
    )
    remaining = parse_int(raw, r"\bremaining\s*=\s*(\d+)")
    return source, remaining


def cancel_run(run_id: object) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    r = requests.post(f"{API}/repos/{REPO}/actions/runs/{rid}/cancel", headers=HEADERS, timeout=30)
    return r.status_code in (201, 202, 204, 409)


def workflow_active(workflow: str) -> bool:
    """Used only for Snapshot/Ledger repair, never semantic Qwen lifecycle."""
    data = api_json(f"/repos/{REPO}/actions/workflows/{workflow}/runs?per_page=30")
    now = datetime.now(timezone.utc)
    max_age = int(MAX_ACTIVE_AGE_BY_WORKFLOW.get(workflow, DEFAULT_MAX_ACTIVE_AGE_MINUTES))
    recent_active = False
    for run in data.get("workflow_runs") or []:
        status = str(run.get("status") or "")
        if status not in ACTIVE_RUN_STATES:
            continue
        ts = _parse_ts(run.get("updated_at") or run.get("run_started_at") or run.get("created_at"))
        age_minutes = (now - ts).total_seconds() / 60 if ts else max_age + 1
        if age_minutes > max_age:
            cancel_run(run.get("id"))
            continue
        recent_active = True
    return recent_active


def dispatch(workflow: str, inputs: dict[str, str] | None = None) -> None:
    payload: dict[str, Any] = {"ref": "main"}
    if inputs:
        payload["inputs"] = {k: str(v) for k, v in inputs.items()}
    r = requests.post(
        f"{API}/repos/{REPO}/actions/workflows/{workflow}/dispatches",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )
    if r.status_code not in (201, 204):
        raise RuntimeError(f"dispatch {workflow}: {r.status_code} {r.text[:800]}")


def current_state() -> StageState:
    qwen_source, qwen_remaining = qwen_release_state()
    return StageState(
        discovery=latest_usable_discovery(),
        snapshot=snapshot_source_run(),
        ledger=ledger_source_run(),
        qwen=qwen_source,
        qwen_remaining=qwen_remaining,
    )


def decide(state: StageState) -> tuple[str, str | None]:
    """Return the first stale or incomplete stage that must be repaired."""
    if not state.discovery:
        return "WAIT_NO_USABLE_DISCOVERY", None
    if state.snapshot != state.discovery:
        return "SNAPSHOT", state.discovery
    if state.ledger != state.discovery:
        return "LEDGER", state.discovery
    if state.qwen != state.discovery:
        return "QWEN", state.discovery
    if state.qwen_remaining is not None and state.qwen_remaining > 0:
        return "QWEN", state.discovery
    return "HEALTHY", state.discovery


def main() -> None:
    state = current_state()
    action, target = decide(state)
    report: dict[str, Any] = {
        "schema": "FRESHNESS_CONVEYOR_WATCHDOG_V3_SINGLE_OWNER_QWEN",
        "state": state.__dict__,
        "decision": action,
        "target_generation": target,
        "dispatched": False,
    }

    if action == "SNAPSHOT" and target:
        if workflow_active(SNAPSHOT_WORKFLOW):
            report["decision"] = "SNAPSHOT_ACTIVE_WAIT"
        else:
            dispatch(SNAPSHOT_WORKFLOW, {"source_discovery_run": target})
            report["dispatched"] = True
    elif action == "LEDGER" and target:
        if workflow_active(LEDGER_WORKFLOW):
            report["decision"] = "LEDGER_ACTIVE_WAIT"
        else:
            dispatch(LEDGER_WORKFLOW)
            report["dispatched"] = True
    elif action == "QWEN" and target:
        # Single-owner invariant: freshness repair NEVER starts/cancels semantic
        # workers. It only wakes the source-aware semantic controller, which owns
        # dedupe, heartbeat health, queue debt and exact one-run dispatch.
        dispatch(QWEN_CONTROLLER_WORKFLOW)
        report["decision"] = "QWEN_CONTROLLER_WAKE"
        report["dispatched"] = True

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
