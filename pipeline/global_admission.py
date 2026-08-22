from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://api.github.com"
GLOBAL_REPO = "walidgdg1-ai/evergreenleadminer"
TENDER_REPO = "walidgdg1-ai/tender-engine"
DEFAULT_POLICY = {
    "github": {"capacity": 20},
    "workloads": {
        "hospitality": {"enabled": False, "weight": 0.0, "min_slots_when_demanding": 0, "max_slots": 0},
        "tenders": {"enabled": True, "weight": 0.5, "min_slots_when_demanding": 10, "max_slots": 20},
        "gws": {"enabled": True, "weight": 0.5, "min_slots_when_demanding": 10, "max_slots": 10},
    },
}


def _request(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "tender-global-admission/2.3"})
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
    if repo.lower().endswith("/tender-engine"):
        if "qwen live notice classification" in blob or "qwen-live-classification" in blob:
            return "qwen-semantic"
        return "tenders"
    if "tender" in blob or "dce" in blob:
        return "tenders"
    if "gws" in blob or "no-website" in blob or "no website" in blob:
        return "gws"
    if "hospitality" in blob or "airbnb" in blob or "property global" in blob:
        return "hospitality"
    return "external"


def _per_page(url: str, n: int = 100) -> str:
    """Return a GitHub REST URL with an explicit high first-page bound."""
    if not url:
        return url
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["per_page"] = str(max(1, min(100, int(n))))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def _repo_capacity_state(repo: str, ignore_run_id: str = "") -> tuple[Counter, Counter]:
    """Return (active slots, queued jobs) by workload/sublane.

    Queued jobs are demand signals, not physical occupancy. Active jobs consume
    hosted-runner slots. Qwen semantic work is tracked separately from generic
    Tender/DCE work so a real semantic reservation can be enforced without
    preempting already-running jobs.
    """
    active: Counter[str] = Counter()
    queued: Counter[str] = Counter()
    seen: set[str] = set()
    for run_status in ("in_progress", "queued"):
        data = _json(f"{API}/repos/{repo}/actions/runs?status={run_status}&per_page=100", {})
        for run in (data or {}).get("workflow_runs") or []:
            rid = str(run.get("id") or "")
            if not rid or rid in seen or rid == ignore_run_id:
                continue
            seen.add(rid)
            workload = _classify(repo, str(run.get("name") or run.get("display_title") or ""), str(run.get("path") or ""))
            jobs = _json(_per_page(str(run.get("jobs_url") or ""), 100), {})
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
    """Identify Qwen-related work for observability."""
    flag = str(os.getenv("DCE_QWEN_LIVE_STREAMING_LANE") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if "qwen_live_selection" in _workflow_selection_path().lower():
        return True
    workflow = str(os.getenv("GITHUB_WORKFLOW") or "").strip().lower()
    return "qwen live notice classification" in workflow


def _semantic_qwen_lane() -> bool:
    """True only for the semantic notice-classification workers themselves."""
    workflow = str(os.getenv("GITHUB_WORKFLOW") or "").strip().lower()
    return "qwen live notice classification" in workflow


def _dce_lane() -> bool:
    if _semantic_qwen_lane():
        return False
    flag = str(os.getenv("DCE_BACKFILL_CAP_LANE") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    workflow = str(os.getenv("GITHUB_WORKFLOW") or "").strip().lower()
    return "dce" in workflow or bool(_workflow_selection_path())


def _qwen_backlog_remaining() -> int:
    """Read the durable semantic backlog conservatively.

    Local main is preferred because every Tender workflow has it after checkout.
    The raw-main fallback keeps admission correct for unusual callers. Failure to
    read the metric returns 0 rather than inventing backlog.
    """
    raw = str(os.getenv("QWEN_BACKLOG_REMAINING") or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except Exception:
            pass
    p = Path("control/qwen_live/classification_summary.json")
    try:
        if p.exists():
            payload = json.loads(p.read_text(encoding="utf-8"))
            return max(0, int(payload.get("remaining_classification_queue") or 0))
    except Exception:
        pass
    payload = _json(f"https://raw.githubusercontent.com/{TENDER_REPO}/main/control/qwen_live/classification_summary.json", {})
    try:
        return max(0, int((payload or {}).get("remaining_classification_queue") or 0))
    except Exception:
        return 0


def _dce_cap_for_qwen_backlog(remaining: int) -> int:
    if remaining >= 50_000:
        return 2
    if remaining >= 20_000:
        return 4
    if remaining >= 5_000:
        return 6
    return 10


def _qwen_semantic_reservation_for_backlog(remaining: int, total: int) -> int:
    """Return the desired non-preemptive semantic floor in hosted-runner slots."""
    if remaining >= 50_000:
        target = 16
    elif remaining >= 20_000:
        target = 14
    elif remaining >= 5_000:
        target = 10
    elif remaining > 0:
        target = 6
    else:
        target = 0
    return min(max(0, int(total)), target)


def dynamic_tender_parallel(requested: int) -> tuple[int, dict]:
    requested = max(0, int(requested))
    requested_before_backfill_cap = requested
    qwen_remaining = _qwen_backlog_remaining()
    dce_backfill_cap = None

    # DCE remains alive during semantic backfill, but is deliberately thin.
    if _dce_lane() and not _spm_curated_fast_lane():
        dce_backfill_cap = _dce_cap_for_qwen_backlog(qwen_remaining)
        requested = min(requested, dce_backfill_cap)

    if _controller_preauthorized():
        hard_cap = 20
        allowed = min(requested, hard_cap)
        return allowed, {
            "mode": "controller-preauthorized-budget",
            "requested": requested_before_backfill_cap,
            "requested_after_qwen_backfill_cap": requested,
            "allowed": allowed,
            "hard_cap": hard_cap,
            "qwen_remaining": qwen_remaining,
            "dce_backfill_cap": dce_backfill_cap,
            "qwen_semantic_reservation_target": _qwen_semantic_reservation_for_backlog(qwen_remaining, hard_cap),
            "authority": "fleet_controller",
            "reason": "controller already performed physical capacity admission; Qwen/DCE backlog caps remain enforced locally",
            "preemption": "none; consume only the controller-approved budget",
        }

    if os.getenv("DCE_DISABLE_GLOBAL_ADMISSION", "").lower() in {"1", "true", "yes"}:
        hard_cap = 20
        allowed = min(requested, hard_cap)
        return allowed, {
            "mode": "disabled-but-physical-hard-cap",
            "requested": requested_before_backfill_cap,
            "requested_after_qwen_backfill_cap": requested,
            "allowed": allowed,
            "hard_cap": hard_cap,
            "qwen_remaining": qwen_remaining,
            "dce_backfill_cap": dce_backfill_cap,
            "qwen_semantic_reservation_target": _qwen_semantic_reservation_for_backlog(qwen_remaining, hard_cap),
        }

    policy = _policy()
    total = max(1, int((policy.get("github") or {}).get("capacity") or 20))
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
    tender_floor = min(total, max(0, int(tender_cfg.get("min_slots_when_demanding") or 10)))
    tender_max = min(total, max(tender_floor, int(tender_cfg.get("max_slots") or tender_floor or total)))
    existing_qwen_semantic_active = int(active.get("qwen-semantic", 0))
    existing_tender_general_active = int(active.get("tenders", 0))
    existing_tender_active = existing_qwen_semantic_active + existing_tender_general_active
    tender_room = max(0, tender_max - existing_tender_active)
    qwen_semantic_reservation_target = _qwen_semantic_reservation_for_backlog(qwen_remaining, total)
    qwen_missing_reserved = max(0, qwen_semantic_reservation_target - existing_qwen_semantic_active)

    if _spm_curated_fast_lane():
        physical_free = max(0, total - active_total)
        qwen_protected_free = max(0, physical_free - qwen_missing_reserved)
        cap = 3
        allowed = min(requested, cap, qwen_protected_free, tender_room)
        return allowed, {
            "mode": "spm-curated-free-slot-fast-lane",
            "capacity": total,
            "requested": requested_before_backfill_cap,
            "allowed": allowed,
            "fast_lane_cap": cap,
            "qwen_remaining": qwen_remaining,
            "active_commitments": dict(active),
            "queued_backlog": dict(queued),
            "active_total": active_total,
            "physical_free": physical_free,
            "qwen_semantic_reservation_target": qwen_semantic_reservation_target,
            "existing_qwen_semantic_active": existing_qwen_semantic_active,
            "queued_qwen_semantic": int(queued.get("qwen-semantic", 0)),
            "qwen_missing_reserved": qwen_missing_reserved,
            "qwen_protected_free": qwen_protected_free,
            "existing_tender_active": existing_tender_active,
            "existing_tender_general_active": existing_tender_general_active,
            "tender_room": tender_room,
            "selection_path": _workflow_selection_path(),
            "workflow": os.getenv("GITHUB_WORKFLOW") or "",
            "preemption": "none; only currently free non-reserved slots are consumed",
            "reason": "GPT-curated SPM DCE shortlist receives bounded latency priority without consuming missing Qwen semantic reservation",
        }

    sibling_targets = {
        "hospitality": _fair_target(total, hospitality_demand, hospitality_cfg),
        "gws": _fair_target(total, gws_demand, gws_cfg),
    }
    sibling_missing = sum(max(0, sibling_targets[w] - int(active.get(w, 0))) for w in sibling_targets)
    physical_free = max(0, total - active_total)
    global_room_after_protection = max(0, physical_free - sibling_missing)
    semantic_lane = _semantic_qwen_lane()
    admission_room_after_qwen_reservation = (
        global_room_after_protection
        if semantic_lane
        else max(0, global_room_after_protection - qwen_missing_reserved)
    )

    effective_tender_demand = max(tender_demand, requested + existing_tender_active)
    unmet_tender_demand = max(0, effective_tender_demand - existing_tender_active)
    allowed = min(requested, admission_room_after_qwen_reservation, tender_room, unmet_tender_demand, tender_max)

    borrowed_slots = max(0, existing_tender_active + allowed - tender_floor)
    report = {
        "mode": "active-slot-fair-share-admission",
        "capacity": total,
        "requested": requested_before_backfill_cap,
        "requested_after_qwen_backfill_cap": requested,
        "allowed": allowed,
        "sublane": "qwen-semantic" if semantic_lane else ("qwen-related" if _qwen_live_streaming_lane() else "tender-general"),
        "qwen_remaining": qwen_remaining,
        "dce_backfill_cap": dce_backfill_cap,
        "active_commitments": dict(active),
        "queued_backlog": dict(queued),
        "active_total": active_total,
        "physical_free": physical_free,
        "demand": {
            "hospitality": hospitality_demand,
            "gws": gws_demand,
            "tenders_remote": tender_demand,
            "tenders_effective": effective_tender_demand,
        },
        "sibling_targets": sibling_targets,
        "sibling_missing_reserved": sibling_missing,
        "global_room_after_protection": global_room_after_protection,
        "qwen_semantic_reservation_target": qwen_semantic_reservation_target,
        "existing_qwen_semantic_active": existing_qwen_semantic_active,
        "queued_qwen_semantic": int(queued.get("qwen-semantic", 0)),
        "qwen_missing_reserved": qwen_missing_reserved,
        "admission_room_after_qwen_reservation": admission_room_after_qwen_reservation,
        "existing_tender_active": existing_tender_active,
        "existing_tender_general_active": existing_tender_general_active,
        "queued_tender_backlog": int(queued.get("tenders", 0)),
        "tender_floor": tender_floor,
        "tender_max": tender_max,
        "borrowed_idle_slots_after_admission": borrowed_slots,
        "preemption": "none; idle borrowing ends naturally as current jobs complete",
        "queue_rule": "queued sibling jobs reserve fair-share capacity; Qwen backlog reserves semantic Tender room; only active jobs consume physical slots",
        "semantic_reservation_rule": "non-Qwen Tender work cannot consume the missing Qwen semantic floor while semantic backlog remains; existing jobs are never preempted",
        "policy_fallback": "Tender floor remains protected while idle capacity may burst up to the configured max; GWS demand keeps its reservation.",
    }
    return allowed, report
