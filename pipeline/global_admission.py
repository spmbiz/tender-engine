from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter

API = "https://api.github.com"
GLOBAL_REPO = "walidgdg1-ai/evergreenleadminer"
DEFAULT_POLICY = {
    "github": {"capacity": 20},
    "workloads": {
        "hospitality": {"enabled": True, "weight": 0.50, "min_slots_when_demanding": 6, "max_slots": 20},
        "tenders": {"enabled": True, "weight": 0.25, "min_slots_when_demanding": 4, "max_slots": 14},
        "gws": {"enabled": True, "weight": 0.25, "min_slots_when_demanding": 4, "max_slots": 10},
    },
}


def _request(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "tender-global-admission/1.0"})
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


def _repo_commitments(repo: str, ignore_run_id: str = "") -> Counter:
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    for status in ("in_progress", "queued"):
        data = _json(f"{API}/repos/{repo}/actions/runs?status={status}&per_page=30", {})
        for run in (data or {}).get("workflow_runs") or []:
            rid = str(run.get("id") or "")
            if not rid or rid in seen or rid == ignore_run_id:
                continue
            seen.add(rid)
            jobs = _json(run.get("jobs_url") or "", {})
            rows = (jobs or {}).get("jobs") or []
            if rows:
                committed = sum(j.get("status") in {"in_progress", "queued"} for j in rows)
            else:
                committed = 1 if run.get("status") in {"in_progress", "queued"} else 0
            if committed:
                w = _classify(repo, str(run.get("name") or run.get("display_title") or ""), str(run.get("path") or ""))
                counts[w] += committed
    return counts


def _fair_target(total: int, demand: int, cfg: dict) -> int:
    if demand <= 0 or not cfg.get("enabled", True):
        return 0
    floor = max(0, int(cfg.get("min_slots_when_demanding") or 0))
    cap = max(0, int(cfg.get("max_slots") or total))
    weighted = int(total * max(0.0, float(cfg.get("weight") or 0.0)))
    return min(demand, cap, max(floor, weighted))


def dynamic_tender_parallel(requested: int) -> tuple[int, dict]:
    """Admission-control new DCE runners without preempting any running job.

    Existing active/queued jobs remain untouched. New Tender shards can borrow
    genuinely idle shares, but cannot consume slots needed to restore a demanding
    sibling workload to its fair target.
    """
    requested = max(0, int(requested))
    if os.getenv("DCE_DISABLE_GLOBAL_ADMISSION", "").lower() in {"1", "true", "yes"}:
        return requested, {"mode": "disabled", "requested": requested, "allowed": requested}

    policy = _policy()
    total = int((policy.get("github") or {}).get("capacity") or 20)
    workloads = policy.get("workloads") or DEFAULT_POLICY["workloads"]
    state = _global_state()
    last = state.get("last_decision") if isinstance(state, dict) else {}
    demand = (last or {}).get("demand") or {}
    # Fail safe toward fairness if the remote demand snapshot is temporarily absent.
    hospitality_demand = int(demand.get("hospitality") or 1)
    gws_demand = int(demand.get("gws") or 0)
    tender_demand = int(demand.get("tenders") or max(requested, 1))

    current_run = str(os.getenv("GITHUB_RUN_ID") or "")
    counts: Counter[str] = Counter()
    counts.update(_repo_commitments(GLOBAL_REPO))
    counts.update(_repo_commitments("walidgdg1-ai/tender-engine", ignore_run_id=current_run))

    sibling_targets = {
        "hospitality": _fair_target(total, hospitality_demand, workloads.get("hospitality") or {}),
        "gws": _fair_target(total, gws_demand, workloads.get("gws") or {}),
    }
    sibling_missing = sum(max(0, sibling_targets[w] - int(counts.get(w, 0))) for w in sibling_targets)
    committed = sum(int(v) for v in counts.values())
    global_room_after_protection = max(0, total - committed - sibling_missing)

    tender_cfg = workloads.get("tenders") or {}
    tender_max = int(tender_cfg.get("max_slots") or total)
    existing_tender = int(counts.get("tenders", 0))
    tender_room = max(0, tender_max - existing_tender)
    allowed = min(requested, global_room_after_protection, tender_room, max(0, tender_demand - existing_tender))

    report = {
        "mode": "fair-share-admission",
        "capacity": total,
        "requested": requested,
        "allowed": allowed,
        "commitments": dict(counts),
        "demand": {"hospitality": hospitality_demand, "gws": gws_demand, "tenders": tender_demand},
        "sibling_targets": sibling_targets,
        "sibling_missing_reserved": sibling_missing,
        "global_room_after_protection": global_room_after_protection,
        "existing_tender_commitment": existing_tender,
        "tender_max": tender_max,
        "preemption": "none; admission control only",
    }
    return allowed, report
