from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter

API = "https://api.github.com"
GLOBAL_REPO = "walidgdg1-ai/evergreenleadminer"
TENDER_REPO = "walidgdg1-ai/tender-engine"
DEFAULT_POLICY = {
    "github": {"capacity": 20},
    "workloads": {
        "hospitality": {"enabled": False, "weight": 0.0, "min_slots_when_demanding": 0, "max_slots": 0},
        "tenders": {"enabled": True, "weight": 0.5, "min_slots_when_demanding": 10, "max_slots": 10},
        "gws": {"enabled": True, "weight": 0.5, "min_slots_when_demanding": 10, "max_slots": 10},
    },
}


def _request(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "tender-global-admission/1.9"})
    tok = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    return req


def _json(url: str, default):
    try:
        with urllib.request.urlopen(_request(url), timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return default


def _policy():
    url = f"https://raw.githubusercontent.com/{GLOBAL_REPO}/main/config/global_fleet.json"
    return _json(url, DEFAULT_POLICY) or DEFAULT_POLICY


def _global_state():
    url = f"https://github.com/{GLOBAL_REPO}/releases/download/global-fleet-broker/global-capacity.json"
    return _json(url, {}) or {}


def _classify(repo: str, name: str, path: str) -> str:
    blob = f"{name} {path}".lower()
    if repo.lower().endswith("/tender-engine") or "tender" in blob or "dce" in blob:
        return "tenders"
    if "gws" in blob or "no-website" in blob or "no website" in blob:
        return "gws"
    if "hospitality" in blob or "airbnb" in blob or "property global" in blob:
        return "hospitality"
    return "external"


def _repo_capacity_state(repo: str, ignore_run_id: str = "") -> tuple[Counter, Counter]:
    """Return (active slots, queued jobs) by workload.

    Queued jobs are backlog/demand signals, not physical occupancy. Active jobs
    consume the 20 hosted-runner slots. Tender (including Qwen) and GWS each have
    a hard 10-slot cap in the personal-account fallback mode.
    """
    active: Counter[str] = Counter()
    queued: Counter[str] = Counter()
    seen: set[str] = set()
    for run_status in ("in_progress", "queued"):
        data = _json(f"{API}/repos/{repo}/actions/runs?status={run_status}&per_page=30", {})
        for run in (data or {}).get("workflow_runs") or []:
            rid = str(run.get("id") or "")
            if not rid or rid in seen or rid == ignore_run_id:
                continue
            seen.add(rid)
            workload = _classify(repo, str(run.get("name") or run.get("display_title") or ""), str(run.get("path") or ""))
            jobs = _json(run.get("jobs_url") or "", {})
            rows = (jobs or {}).get("jobs") or []
            if rows:
                active[workload] += sum(j.get("status") == "in_progress" for j in rows)
                queued[workload] += sum(j.get("status") == "queued" for j in rows)
            elif run_status == "in_progress":
                active[workload] += 1
            elif run_status == "queued":
                queued[workload] += 1
    return active, queued


def _fair_target(total: int, demand: int, cfg: dict) -> int:
    if demand <= 0 or not cfg.get("enabled", True):
        return 0
    floor = max(0, int(cfg.get("min_slots_when_demanding") or 0))
    cap = max(0, int(cfg.get("max_slots") or total))
    weighted = int(total * max(0.0, float(cfg.get("weight") or 0.0)))
    return min(demand, cap, max(floor, weighted))


def _controller_preauthorized() -> bool:
    flag = str(os.getenv("DCE_ADMISSION_PREAUTHORIZED") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    ref_name = str(os.getenv("GITHUB_REF_NAME") or "").strip()
    if not ref_name:
        ref = str(os.getenv("GITHUB_REF") or "").strip()
        if ref.startswith("refs/heads/"):
            ref_name = ref[len("refs/heads/"):]
    return ref_name == "fleet-dce"


def _workflow_selection_path() -> str:
    explicit = str(os.getenv("DCE_SELECTION_PATH") or "").strip()
    if explicit:
        return explicit
    event_path = str(os.getenv("GITHUB_EVENT_PATH") or "").strip()
    if not event_path:
        return ""
    try:
        event = json.load(open(event_path, encoding="utf-8"))
    except Exception:
        return ""
    inputs = event.get("inputs") if isinstance(event, dict) else {}
    if not isinstance(inputs, dict):
        return ""
    return str(inputs.get("selection_path") or "").strip()


def _spm_curated_fast_lane() -> bool:
    flag = str(os.getenv("DCE_SPM_CURATED_FAST_LANE") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return "spm_rescue_selection" in _workflow_selection_path().lower()


def _qwen_live_streaming_lane() -> bool:
    """Identify Qwen work for observability only.

    Qwen is deliberately NOT a separate capacity pool. The classifier and its DCE
    handoff are normal Tender work and consume the same 10-slot Tender share.
    """
    flag = str(os.getenv("DCE_QWEN_LIVE_STREAMING_LANE") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if "qwen_live_selection" in _workflow_selection_path().lower():
        return True
    workflow = str(os.getenv("GITHUB_WORKFLOW") or "").strip().lower()
    return "qwen live notice classification" in workflow


def dynamic_tender_parallel(requested: int) -> tuple[int, dict]:
    requested = max(0, int(requested))
    if _controller_preauthorized():
        allowed = min(requested, 10)
        return allowed, {
            "mode": "controller-preauthorized-budget",
            "requested": requested,
            "allowed": allowed,
            "hard_cap": 10,
            "authority": "fleet_controller",
            "reason": "controller already performed capacity admission; personal-account Tender hard cap remains 10",
            "preemption": "none; consume only the controller-approved budget",
        }
    if os.getenv("DCE_DISABLE_GLOBAL_ADMISSION", "").lower() in {"1", "true", "yes"}:
        allowed = min(requested, 10)
        return allowed, {"mode": "disabled-but-personal-hard-cap", "requested": requested, "allowed": allowed, "hard_cap": 10}

    policy = _policy()
    total = int((policy.get("github") or {}).get("capacity") or 20)
    workloads = policy.get("workloads") or DEFAULT_POLICY["workloads"]
    state = _global_state()
    last = state.get("last_decision") if isinstance(state, dict) else {}
    demand = (last or {}).get("demand") or {}

    hospitality_cfg = workloads.get("hospitality") or {}
    gws_cfg = workloads.get("gws") or {}
    hospitality_floor = max(0, int(hospitality_cfg.get("min_slots_when_demanding") or 0))
    gws_floor = max(0, int(gws_cfg.get("min_slots_when_demanding") or 10))
    hospitality_demand = int(demand.get("hospitality") or 0)
    gws_demand = int(demand.get("gws") or 0)
    tender_demand = int(demand.get("tenders") or max(requested, 1))

    current_run = str(os.getenv("GITHUB_RUN_ID") or "")
    active: Counter[str] = Counter()
    queued: Counter[str] = Counter()
    for repo, ignore in ((GLOBAL_REPO, ""), (TENDER_REPO, current_run)):
        repo_active, repo_queued = _repo_capacity_state(repo, ignore_run_id=ignore)
        active.update(repo_active)
        queued.update(repo_queued)

    hospitality_visible = int(active.get("hospitality", 0)) + int(queued.get("hospitality", 0))
    gws_visible = int(active.get("gws", 0)) + int(queued.get("gws", 0))
    if hospitality_demand <= 0 and hospitality_visible > 0:
        hospitality_demand = max(hospitality_floor, hospitality_visible)
    if gws_demand <= 0 and gws_visible > 0:
        gws_demand = max(gws_floor, gws_visible)

    active_total = sum(int(v) for v in active.values())
    tender_cfg = workloads.get("tenders") or {}
    tender_max = min(10, int(tender_cfg.get("max_slots") or 10))
    existing_tender_active = int(active.get("tenders", 0))
    tender_room = max(0, tender_max - existing_tender_active)

    if _spm_curated_fast_lane():
        physical_free = max(0, total - active_total)
        cap = 3
        allowed = min(requested, cap, physical_free, tender_room)
        return allowed, {
            "mode": "spm-curated-free-slot-fast-lane",
            "capacity": total,
            "requested": requested,
            "allowed": allowed,
            "fast_lane_cap": cap,
            "active_commitments": dict(active),
            "queued_backlog": dict(queued),
            "active_total": active_total,
            "physical_free": physical_free,
            "existing_tender_active": existing_tender_active,
            "tender_room": tender_room,
            "selection_path": _workflow_selection_path(),
            "workflow": os.getenv("GITHUB_WORKFLOW") or "",
            "preemption": "none; only currently free physical slots are consumed",
            "reason": "GPT-curated SPM DCE shortlist receives bounded latency priority",
        }

    sibling_targets = {
        "hospitality": _fair_target(total, hospitality_demand, hospitality_cfg),
        "gws": _fair_target(total, gws_demand, gws_cfg),
    }
    sibling_missing = sum(max(0, sibling_targets[w] - int(active.get(w, 0))) for w in sibling_targets)
    global_room_after_protection = max(0, total - active_total - sibling_missing)

    effective_tender_demand = max(tender_demand, requested + existing_tender_active)
    unmet_tender_demand = max(0, effective_tender_demand - existing_tender_active)
    allowed = min(requested, global_room_after_protection, tender_room, unmet_tender_demand, 10)

    report = {
        "mode": "personal-10-10-tender-admission",
        "capacity": total,
        "requested": requested,
        "allowed": allowed,
        "sublane": "qwen" if _qwen_live_streaming_lane() else "tender-general",
        "active_commitments": dict(active),
        "queued_backlog": dict(queued),
        "active_total": active_total,
        "demand": {
            "hospitality": hospitality_demand,
            "gws": gws_demand,
            "tenders_remote": tender_demand,
            "tenders_effective": effective_tender_demand,
        },
        "sibling_targets": sibling_targets,
        "sibling_missing_reserved": sibling_missing,
        "global_room_after_protection": global_room_after_protection,
        "existing_tender_active": existing_tender_active,
        "queued_tender_backlog": int(queued.get("tenders", 0)),
        "tender_max": tender_max,
        "preemption": "none; admission control only",
        "queue_rule": "queued jobs signal demand; only active jobs consume physical runner capacity",
        "policy_fallback": "10 tenders (Qwen included) + 10 GWS; Hospitality fanout paused while on personal 20-slot capacity",
    }
    return allowed, report
