#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

HEARTBEAT_FRESH_MINUTES = 30.0
STARTUP_GRACE_MINUTES = 35.0
API_UNKNOWN_GRACE_MINUTES = 145.0
FRESH_QUEUED_GRACE_MINUTES = 10.0
ACTIVE_QUEUE_STATES = {"queued", "waiting", "pending", "requested"}


def parse_dt(value: object) -> dt.datetime | None:
    if not value:
        return None
    try:
        out = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def age_minutes(created_at: object, now: dt.datetime) -> float:
    created = parse_dt(created_at)
    if created is None:
        return 1e9
    return max(0.0, (now - created).total_seconds() / 60.0)


def _rid(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("databaseId"))
    except Exception:
        return None


def decide(
    *,
    now: dt.datetime,
    remaining: int | None,
    ledger_source: int | None,
    semantic_source: int | None,
    runs: list[dict[str, Any]],
    heartbeats: dict[int, dict[str, Any]],
    heartbeat_fresh_minutes: float = HEARTBEAT_FRESH_MINUTES,
    startup_grace_minutes: float = STARTUP_GRACE_MINUTES,
    api_unknown_grace_minutes: float = API_UNKNOWN_GRACE_MINUTES,
    queued_grace_minutes: float = FRESH_QUEUED_GRACE_MINUTES,
) -> dict[str, Any]:
    """Pure semantic-lane decision logic.

    A queued workflow is never health. One healthy in-progress generation is kept.
    Fresh heartbeat always wins over elapsed age. API uncertainty fails safe close
    to the worker timeout. A newer ledger generation counts as backlog even when
    the prior semantic summary says zero.
    """
    running = [r for r in runs if r.get("status") == "in_progress"]
    queued = [r for r in runs if r.get("status") in ACTIVE_QUEUE_STATES]

    running_info: list[dict[str, Any]] = []
    for row in running:
        run_id = _rid(row)
        if run_id is None:
            continue
        age = age_minutes(row.get("createdAt"), now)
        hb = heartbeats.get(run_id) or {"state": "missing", "age_minutes": None}
        hb_state = str(hb.get("state") or "missing")
        try:
            hb_age = float(hb["age_minutes"]) if hb.get("age_minutes") is not None else None
        except Exception:
            hb_age = None
        heartbeat_ok = hb_state == "ok" and hb_age is not None and hb_age <= heartbeat_fresh_minutes
        heartbeat_stale = hb_state == "ok" and hb_age is not None and hb_age > heartbeat_fresh_minutes
        startup_ok = hb_state == "missing" and age < startup_grace_minutes
        api_unknown_ok = hb_state == "unknown" and age < api_unknown_grace_minutes
        healthy = heartbeat_ok or startup_ok or api_unknown_ok
        running_info.append(
            {
                "id": run_id,
                "age_minutes": round(age, 1),
                "heartbeat_state": hb_state,
                "heartbeat_age_minutes": round(hb_age, 1) if hb_age is not None else None,
                "heartbeat_ok": heartbeat_ok,
                "heartbeat_stale": heartbeat_stale,
                "startup_grace": startup_ok,
                "api_unknown_grace": api_unknown_ok,
                "healthy": healthy,
            }
        )

    healthy_runs = [x for x in running_info if x["healthy"]]
    healthy_runs.sort(
        key=lambda x: (
            not x["heartbeat_ok"],
            x["heartbeat_age_minutes"] if x["heartbeat_age_minutes"] is not None else 1e9,
            x["age_minutes"],
        )
    )
    keeper = healthy_runs[0] if healthy_runs else None
    running_cancel = [x["id"] for x in running_info if keeper is None or x["id"] != keeper["id"]]

    queued_info: list[dict[str, Any]] = []
    for row in queued:
        run_id = _rid(row)
        if run_id is None:
            continue
        queued_info.append(
            {
                "id": run_id,
                "event": str(row.get("event") or ""),
                "age_minutes": round(age_minutes(row.get("createdAt"), now), 1),
            }
        )

    queued_keeper = None
    if keeper is None:
        candidates = [
            x
            for x in queued_info
            if x["event"] == "workflow_dispatch" and x["age_minutes"] < queued_grace_minutes
        ]
        candidates.sort(key=lambda x: x["age_minutes"])
        if candidates:
            queued_keeper = candidates[0]
    queued_cancel = [x["id"] for x in queued_info if queued_keeper is None or x["id"] != queued_keeper["id"]]

    source_gap = bool(
        ledger_source is not None
        and (semantic_source is None or int(ledger_source) > int(semantic_source))
    )
    has_backlog = remaining is None or remaining > 0 or source_gap
    covered = keeper is not None or queued_keeper is not None
    cancel_ids = running_cancel + queued_cancel

    return {
        "remaining": remaining if remaining is not None else "unknown",
        "ledger_source": ledger_source,
        "semantic_source": semantic_source,
        "source_gap": source_gap,
        "has_backlog_or_new_source": has_backlog,
        "running": running_info,
        "running_keeper": keeper,
        "queued": queued_info,
        "queued_keeper": queued_keeper,
        "cancel_ids": cancel_ids,
        "cancel_count": len(cancel_ids),
        "need_dispatch": bool(has_backlog and not covered),
        "lane_covered": covered,
        "policy": {
            "single_running_generation": True,
            "queued_is_health": False,
            "newer_ledger_is_backlog": True,
            "fresh_heartbeat_overrides_elapsed_age": True,
            "heartbeat_fresh_minutes": heartbeat_fresh_minutes,
            "startup_grace_minutes": startup_grace_minutes,
            "api_unknown_grace_minutes": api_unknown_grace_minutes,
            "fresh_queued_dispatch_grace_minutes": queued_grace_minutes,
        },
    }


def gh(*args: str, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["gh", *args], text=True, capture_output=True)
    if proc.returncode and not allow_failure:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def release_source(repo: str, tag: str, key: str) -> int | None:
    proc = gh("release", "view", tag, "--repo", repo, "--json", "body,name", allow_failure=True)
    if proc.returncode:
        return None
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        return None
    text = f"{payload.get('body') or ''} {payload.get('name') or ''}"
    m = re.search(rf"\b{re.escape(key)}=([0-9]+)\b", text)
    if m:
        return int(m.group(1))
    if key == "run":
        nums = re.findall(r"[0-9]{8,}", text)
        if nums:
            return int(nums[-1])
    return None


def heartbeat_probe(repo: str, run_id: int, now: dt.datetime) -> dict[str, Any]:
    proc = gh("api", f"repos/{repo}/releases/tags/qwen-live-progress-{run_id}", allow_failure=True)
    if proc.returncode:
        err = (proc.stderr or "").lower()
        if "404" in err or "not found" in err:
            return {"state": "missing", "age_minutes": None}
        return {"state": "unknown", "age_minutes": None, "error": (proc.stderr or "")[-500:]}
    try:
        rel = json.loads(proc.stdout)
    except Exception:
        return {"state": "unknown", "age_minutes": None, "error": "invalid release JSON"}
    stamps = []
    for asset in rel.get("assets") or []:
        stamp = parse_dt(asset.get("updated_at") or asset.get("created_at"))
        if stamp:
            stamps.append(stamp)
    if not stamps:
        return {"state": "missing", "age_minutes": None}
    latest = max(stamps)
    return {
        "state": "ok",
        "age_minutes": max(0.0, (now - latest).total_seconds() / 60.0),
        "latest_at": latest.isoformat(),
    }


def inspect(repo: str, summary_path: Path) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    remaining = None
    generated_at = None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        remaining = max(0, int(summary.get("remaining_classification_queue")))
        generated_at = summary.get("generated_at")
    except Exception:
        pass

    ledger_source = release_source(repo, "notice-intelligence-ledger-latest", "run")
    semantic_source = release_source(repo, "qwen-classification-state-latest", "source_run")
    proc = gh(
        "run", "list", "--repo", repo, "--workflow", "qwen-live-classification.yml",
        "--limit", "100", "--json", "databaseId,status,conclusion,createdAt,updatedAt,event,url",
    )
    runs = json.loads(proc.stdout or "[]")
    heartbeats: dict[int, dict[str, Any]] = {}
    for row in runs:
        if row.get("status") != "in_progress":
            continue
        run_id = _rid(row)
        if run_id is not None:
            heartbeats[run_id] = heartbeat_probe(repo, run_id, now)

    out = decide(
        now=now,
        remaining=remaining,
        ledger_source=ledger_source,
        semantic_source=semantic_source,
        runs=runs,
        heartbeats=heartbeats,
    )
    out["inspected_at"] = now.isoformat()
    out["summary_generated_at"] = generated_at
    out["heartbeats"] = heartbeats
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "walidgdg1-ai/tender-engine"))
    ap.add_argument("--summary", default="control/qwen_live/classification_summary.json")
    ap.add_argument("--out", default="/tmp/qwen-controller-decision.json")
    args = ap.parse_args()
    result = inspect(args.repo, Path(args.summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
