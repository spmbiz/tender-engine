from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

GREEN_CLASSES = {"FINAL_SUPER_GREEN", "GREEN", "GREEN_PARTNERABLE"}
REVIEW_CLASS = "MODEL_REVIEW_REQUIRED"
CLASS_RANK = {"FINAL_SUPER_GREEN": 4, "GREEN": 3, "GREEN_PARTNERABLE": 2}
RESOLVED_DEADLINE = {
    "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE",
    "DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING",
}
RESOLVED_GATE_STATUSES = {"PASS", "PASS_CONDITIONAL", "NOT_APPLICABLE"}

# Post-DCE ranking is deliberately NOT a hard eligibility filter. Discovery remains
# recall-first. This rank only decides what ChatGPT should read first once we already
# possess authoritative DCE evidence.
SPM_POSITIVE_SIGNALS: tuple[tuple[str, int, str], ...] = (
    ("website redesign", 48, "website-redesign"),
    ("website development", 48, "website-development"),
    ("web development", 46, "web-development"),
    ("web design", 46, "web-design"),
    ("web portal", 46, "web-portal"),
    ("web application", 44, "web-application"),
    ("landing page", 43, "landing-page"),
    ("cms migration", 42, "cms-migration"),
    ("website migration", 42, "website-migration"),
    ("wordpress", 38, "wordpress"),
    ("drupal", 38, "drupal"),
    ("graphic design", 46, "graphic-design"),
    ("visual identity", 44, "visual-identity"),
    ("brand identity", 44, "brand-identity"),
    ("typesetting", 39, "typesetting"),
    ("publication design", 42, "publication-design"),
    ("video production", 46, "video-production"),
    ("video editing", 48, "video-editing"),
    ("motion graphics", 46, "motion-graphics"),
    ("post-production", 42, "post-production"),
    ("animation production", 43, "animation-production"),
    ("social media management", 44, "social-media"),
    ("social media content", 44, "social-content"),
    ("digital marketing", 40, "digital-marketing"),
    ("content creation", 40, "content-creation"),
    ("copywriting", 38, "copywriting"),
    ("transcription", 48, "transcription"),
    ("subtitling", 46, "subtitling"),
    ("captioning", 44, "captioning"),
    ("printing services", 43, "printing-services"),
    ("printing service", 43, "printing-service"),
    ("brochure printing", 46, "brochure-printing"),
    ("booklet printing", 46, "booklet-printing"),
    ("publication printing", 44, "publication-printing"),
    ("workflow automation", 46, "workflow-automation"),
    ("robotic process automation", 45, "rpa"),
    ("rpa development", 45, "rpa-development"),
    ("api integration", 44, "api-integration"),
    ("application development", 42, "application-development"),
    ("app development", 42, "app-development"),
    ("software development", 40, "software-development"),
    ("data migration", 38, "data-migration"),
    ("system integration", 36, "system-integration"),
    ("systems integration", 36, "systems-integration"),
    ("low-code", 40, "low-code"),
    ("low code", 40, "low-code"),
    ("digital skills training", 38, "digital-training"),
    ("digital training", 36, "digital-training"),
    ("it training", 34, "it-training"),
    ("software training", 34, "software-training"),
    ("e-learning", 40, "e-learning"),
    ("e learning", 40, "e-learning"),
    ("learning management system", 42, "lms"),
    ("lms development", 44, "lms-development"),
)

SPM_BROAD_SIGNALS: tuple[tuple[str, int, str], ...] = (
    ("software maintenance", 20, "software-maintenance"),
    ("application support", 20, "application-support"),
    ("software services", 18, "software-services"),
    ("it services", 16, "it-services"),
    ("ict services", 16, "ict-services"),
    ("digital services", 18, "digital-services"),
    ("digital platform", 20, "digital-platform"),
    ("cloud services", 14, "cloud-services"),
    ("data services", 14, "data-services"),
    ("communications services", 18, "communications"),
    ("public relations", 20, "public-relations"),
    ("training services", 14, "training-services"),
    ("training course", 14, "training-course"),
    ("workshop", 12, "workshop"),
    ("software licenses", 16, "software-resale"),
    ("software licences", 16, "software-resale"),
)

SPM_NEGATIVE_SIGNALS: tuple[tuple[str, int, str], ...] = (
    ("no award will be made", -55, "rfi-no-award"),
    ("not a request for proposal", -45, "not-a-solicitation"),
    ("for information and planning purposes only", -40, "market-research-only"),
    ("100% total small business set-aside", -38, "us-small-business-set-aside"),
    ("set-aside for small business concerns", -34, "us-small-business-set-aside"),
    ("all employees involved in the project must be u.s. citizens", -65, "us-citizens-only"),
    ("must be u.s. citizens", -58, "us-citizens-only"),
    ("u.s. citizens only", -58, "us-citizens-only"),
    ("top secret clearance", -65, "top-secret-clearance"),
    ("top secret", -58, "top-secret-clearance"),
    ("sci eligible", -55, "sci-eligibility"),
    ("security clearance", -42, "security-clearance"),
    ("travel within austere environments", -45, "austere-travel"),
    ("work on a government installation", -24, "government-installation"),
    ("on-site support", -18, "onsite-support"),
    ("onsite support", -18, "onsite-support"),
    ("on site support", -18, "onsite-support"),
    ("protected health information", -15, "phi-security"),
    ("business associate agreement", -15, "baa-security"),
    ("fisma", -15, "fisma"),
    ("cmmc", -20, "cmmc"),
    ("24x7", -12, "24x7-operations"),
    ("24/7", -12, "24x7-operations"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_records(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if Path(path).suffix.lower() == ".jsonl":
        return [json.loads(x) for x in text.splitlines() if x.strip()]
    obj = json.loads(text)
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        return [x for x in obj["items"] if isinstance(x, dict)]
    return [obj] if isinstance(obj, dict) else []


def item_key(r: dict[str, Any]) -> str:
    cid = str(r.get("candidate_id") or "").strip().casefold()
    if cid:
        return cid
    return "|".join(str(r.get(k) or "").strip().casefold() for k in ("title", "buyer", "notice_url"))


def _evidence_text(r: dict[str, Any], max_chars: int = 30000) -> str:
    chunks: list[str] = []
    evidence = r.get("gate_evidence_candidates") or r.get("evidence_by_gate") or {}
    if isinstance(evidence, dict):
        ordered = (
            "deliverables_scope", "sla_onsite", "staffing_team", "certifications_partner",
            "entity_geography", "subcontracting", "ip_data_security", "submission",
            "references_experience", "insurance_bonds", "award_criteria",
        )
        seen = set()
        for gate in ordered + tuple(k for k in evidence.keys() if k not in ordered):
            if gate in seen:
                continue
            seen.add(gate)
            rows = evidence.get(gate) or []
            if not isinstance(rows, list):
                continue
            for row in rows[:4]:
                if isinstance(row, dict):
                    chunks.append(str(row.get("text") or ""))
                elif isinstance(row, str):
                    chunks.append(row)
                if sum(len(x) for x in chunks) >= max_chars:
                    break
            if sum(len(x) for x in chunks) >= max_chars:
                break
    return re.sub(r"\s+", " ", " ".join(chunks))[:max_chars].casefold()


def spm_post_dce_rank(r: dict[str, Any]) -> tuple[int, str, list[str], list[str]]:
    """Rank review attention, never decide eligibility."""
    title = re.sub(r"\s+", " ", str(r.get("title") or "")).casefold()
    evidence = _evidence_text(r)
    full = f" {title} {evidence} "
    score = 0
    reasons: list[str] = []
    blockers: list[str] = []

    for phrase, pts, label in SPM_POSITIVE_SIGNALS:
        if phrase in title:
            score = max(score, pts)
            if label not in reasons:
                reasons.append(label)
        elif phrase in evidence:
            score = max(score, max(8, int(round(pts * 0.65))))
            if label not in reasons:
                reasons.append(label)

    for phrase, pts, label in SPM_BROAD_SIGNALS:
        if phrase in title:
            score = max(score, pts)
            if label not in reasons:
                reasons.append(label)
        elif phrase in evidence:
            score = max(score, max(5, int(round(pts * 0.55))))
            if label not in reasons:
                reasons.append(label)

    coverage = int(r.get("evidence_gate_coverage") or 0)
    priority = int(r.get("priority_score") or r.get("preliminary_score") or 0)
    score += min(12, coverage)
    score += min(12, max(0, priority) // 8)
    if bool(r.get("deadline_resolved")):
        score += 5

    for phrase, penalty, label in SPM_NEGATIVE_SIGNALS:
        if phrase in full:
            score += penalty
            if label not in blockers:
                blockers.append(label)

    score = max(-100, min(100, score))
    if score >= 65:
        band = "HOT"
    elif score >= 40:
        band = "GOOD"
    elif score >= 20:
        band = "MAYBE"
    else:
        band = "LOW"
    return score, band, reasons[:8], blockers[:8]


def compact_green(r: dict[str, Any], run_id: str, shard: str, ts: str) -> dict[str, Any]:
    gates = r.get("gates") or {}
    statuses = {
        str(name): str(item.get("status") or "UNKNOWN").upper()
        for name, item in gates.items()
        if isinstance(item, dict)
    }
    cls = str(r.get("classification") or "").upper()
    return {
        "candidate_id": r.get("candidate_id"), "title": r.get("title"), "buyer": r.get("buyer"),
        "portal": r.get("portal"), "notice_url": r.get("notice_url"), "deadline": r.get("deadline"),
        "estimated_value": r.get("estimated_value"), "currency": r.get("currency"),
        "classification": cls, "final_score": int(r.get("final_score") or 0), "summary": r.get("summary"),
        "content_quality": r.get("content_quality"), "gate_readiness": bool(r.get("gate_readiness")),
        "gate_statuses": statuses,
        "unresolved_gates": [k for k, v in statuses.items() if v not in RESOLVED_GATE_STATUSES],
        "hard_fail_gates": [k for k, v in statuses.items() if v == "FAIL_HARD"],
        "authority_conflicts": r.get("authority_conflicts") or {},
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "source_shard": int(shard) if str(shard).isdigit() else shard,
        "hot_published_at": ts,
    }


def green_sort(r: dict[str, Any]):
    return (
        CLASS_RANK.get(str(r.get("classification") or "").upper(), -1),
        int(r.get("final_score") or 0),
        str(r.get("hot_published_at") or ""),
    )


def merge_green(existing: dict[str, Any], incoming: list[dict[str, Any]], run_id: str, shard: str, max_green: int):
    merged: dict[str, dict[str, Any]] = {}
    for bucket in ("final_supergreens", "greens"):
        for r in existing.get(bucket) or []:
            if isinstance(r, dict):
                merged[item_key(r)] = r
    for r in incoming:
        k = item_key(r)
        cur = merged.get(k)
        if cur is None or green_sort(r) >= green_sort(cur):
            merged[k] = r
    items = sorted(merged.values(), key=green_sort, reverse=True)
    finals = [x for x in items if x.get("classification") == "FINAL_SUPER_GREEN"][:max_green]
    greens = [x for x in items if x.get("classification") in {"GREEN", "GREEN_PARTNERABLE"}][:max_green]
    runs: list[str] = []
    for value in [run_id] + list(existing.get("source_runs") or []):
        s = str(value).strip()
        if s and s not in runs:
            runs.append(s)
    return {
        "schema": "SUPERGREEN_HOT_V1", "updated_at": utc_now(),
        "latest_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "latest_shard": int(shard) if str(shard).isdigit() else shard,
        "source_runs": runs[:20],
        "counts": {"final_supergreen": len(finals), "green_or_partnerable": len(greens)},
        "final_supergreens": finals, "greens": greens,
        "rule": "Hot green cache only. FINAL_SUPER_GREEN remains valid only when produced from authoritative DCE evidence and accepted by final_verdict_guard.py.",
    }


def deadline_info(r: dict[str, Any]):
    authority = r.get("authority_conflicts") or {}
    deadline = authority.get("deadline") if isinstance(authority, dict) else {}
    deadline = deadline if isinstance(deadline, dict) else {}
    status = str(deadline.get("status") or "MISSING")
    return deadline, status, status in RESOLVED_DEADLINE and not bool(deadline.get("conflict"))


def compact_review(r: dict[str, Any], run_id: str, shard: str, ts: str) -> dict[str, Any]:
    evidence = r.get("gate_evidence_candidates") or {}
    coverage = sum(1 for x in evidence.values() if isinstance(x, list) and x)
    deadline, deadline_status, deadline_resolved = deadline_info(r)
    out = {
        "candidate_id": r.get("candidate_id"), "title": r.get("title"), "buyer": r.get("buyer"),
        "portal": r.get("portal"), "notice_url": r.get("notice_url"), "deadline": r.get("deadline"),
        "estimated_value": r.get("estimated_value"), "currency": r.get("currency"),
        "preliminary_score": r.get("preliminary_score"), "priority_score": int(r.get("final_score") or 0),
        "content_quality": r.get("content_quality"), "gate_readiness": bool(r.get("gate_readiness")),
        "deadline_authority": deadline, "deadline_authority_status": deadline_status,
        "deadline_resolved": deadline_resolved, "evidence_gate_coverage": coverage,
        "evidence_by_gate": evidence,
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "source_shard": int(shard) if str(shard).isdigit() else shard,
        "hot_ready_at": ts,
        "review_contract": "Gate-ready authoritative DCE evidence pack from the current DCE generation. Unknown is never PASS. FINAL_SUPER_GREEN requires every mandatory gate resolved and authoritative deadline reconciliation.",
    }
    score, band, reasons, blockers = spm_post_dce_rank(out)
    out["spm_post_dce_score"] = score
    out["spm_fit_band"] = band
    out["spm_fit_reasons"] = reasons
    out["spm_friction_signals"] = blockers
    return out


def ensure_review_rank(r: dict[str, Any]) -> dict[str, Any]:
    score, band, reasons, blockers = spm_post_dce_rank(r)
    r = dict(r)
    r["spm_post_dce_score"] = score
    r["spm_fit_band"] = band
    r["spm_fit_reasons"] = reasons
    r["spm_friction_signals"] = blockers
    return r


def deadline_open(r: dict[str, Any]) -> bool:
    try:
        return date.fromisoformat(str(r.get("deadline") or "")[:10]) >= datetime.now(timezone.utc).date()
    except Exception:
        return True


def review_sort(r: dict[str, Any]):
    return (
        int(r.get("spm_post_dce_score") or -100),
        bool(r.get("deadline_resolved")),
        int(r.get("evidence_gate_coverage") or 0),
        int(r.get("priority_score") or 0),
        str(r.get("hot_ready_at") or ""),
    )


def exploration_sort(r: dict[str, Any]):
    return (
        int(r.get("evidence_gate_coverage") or 0),
        bool(r.get("deadline_resolved")),
        int(r.get("priority_score") or 0),
        str(r.get("hot_ready_at") or ""),
    )


def _run_number(value: Any):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def merge_review(
    existing: dict[str, Any], incoming: list[dict[str, Any]], resolved_keys: set[str],
    run_id: str, shard: str, max_items: int,
):
    """Current-generation bank: ~80% SPM priority + ~20% exploration."""
    incoming_run = _run_number(run_id)
    current_run = _run_number(existing.get("latest_dce_run_id"))
    if incoming_run is not None and current_run is not None and incoming_run < current_run:
        return existing
    reset = bool(incoming_run is not None and current_run is not None and incoming_run > current_run)
    merged: dict[str, dict[str, Any]] = {}
    if not reset:
        for row in existing.get("items") or []:
            if isinstance(row, dict) and item_key(row) not in resolved_keys and deadline_open(row):
                ranked = ensure_review_rank(row)
                merged[item_key(ranked)] = ranked
    for row in incoming:
        if not deadline_open(row):
            continue
        ranked = ensure_review_rank(row)
        k = item_key(ranked)
        cur = merged.get(k)
        if cur is None or review_sort(ranked) >= review_sort(cur):
            merged[k] = ranked

    all_items = list(merged.values())
    if max_items <= 0:
        items: list[dict[str, Any]] = []
    else:
        explore_n = min(max_items, max(3, int(round(max_items * 0.20))))
        priority_n = max(0, max_items - explore_n)
        priority = sorted(all_items, key=review_sort, reverse=True)[:priority_n]
        chosen = {item_key(x) for x in priority}
        exploration = [x for x in sorted(all_items, key=exploration_sort, reverse=True) if item_key(x) not in chosen][:explore_n]
        for row in priority:
            row["review_lane"] = "SPM_PRIORITY"
        for row in exploration:
            row["review_lane"] = "EXPLORATION"
        items = priority + exploration

    return {
        "schema": "GPT_REVIEW_HOT_V3", "updated_at": utc_now(),
        "latest_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "latest_shard": int(shard) if str(shard).isdigit() else shard,
        "generation_reset": reset, "count": len(items), "items": items,
        "ranking_contract": "Recall-first discovery; post-DCE SPM-fit reranking only. Approximately 80% priority lane + 20% evidence-quality exploration lane. No candidate is declared eligible by this rank.",
        "instruction": "Review SPM_PRIORITY HOT/GOOD items first, then exploration. These are authoritative DCE evidence packs, not final verdicts. Unknown is never PASS.",
    }


def gh_get(repo: str, path: str, branch: str, token: str):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "tender-hot-publisher/3.0"}
    resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    if resp.status_code == 404:
        return {}, None
    resp.raise_for_status()
    obj = resp.json()
    raw = base64.b64decode(obj.get("content") or b"").decode("utf-8", errors="replace")
    try:
        cur = json.loads(raw) if raw.strip() else {}
    except Exception:
        cur = {}
    return cur if isinstance(cur, dict) else {}, obj.get("sha")


def gh_put(repo: str, path: str, branch: str, token: str, payload: dict[str, Any], sha: str | None, msg: str):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "tender-hot-publisher/3.0"}
    body = {"message": msg, "content": base64.b64encode((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()).decode(), "branch": branch}
    if sha:
        body["sha"] = sha
    return requests.put(url, headers=headers, json=body, timeout=45)


def publish(repo: str, path: str, branch: str, token: str, builder, msg: str, attempts: int):
    last = None
    for n in range(1, max(1, attempts) + 1):
        try:
            cur, sha = gh_get(repo, path, branch, token)
            payload = builder(cur)
            resp = gh_put(repo, path, branch, token, payload, sha, msg)
            if resp.status_code in {200, 201}:
                return {"published": True, "attempt": n, "path": path, "payload": payload}
            last = f"GitHub PUT {resp.status_code}: {resp.text[:800]}"
            if resp.status_code not in {409, 422}:
                raise RuntimeError(last)
        except Exception as exc:
            last = str(exc)
        if n < attempts:
            time.sleep(min(8.0, 0.35 * n + random.random() * 0.9))
    raise RuntimeError(f"publish failed for {path}: {last}")


def publish_live_inbox(repo: str, branch: str, token: str, run_id: str, shard: str, attempts: int):
    """Rebuild the user-facing inbox transactionally from freshest state."""
    import subprocess
    import sys
    import tempfile

    script = str(Path(__file__).with_name("refresh_gpt_inbox_live.py"))

    def builder(current_existing: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="tender-inbox-") as td:
            local: dict[str, str] = {}
            sources: dict[str, dict[str, Any]] = {"existing": current_existing}
            for name, remote in {
                "final_bank": "control/final_supergreen_bank.json",
                "hot_green": "control/supergreen_hot.json",
                "hot_review": "control/gpt_review_hot.json",
            }.items():
                obj, _ = gh_get(repo, remote, branch, token)
                sources[name] = obj
            for name, obj in sources.items():
                lp = Path(td) / f"{name}.json"
                lp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                local[name] = str(lp)
            out = str(Path(td) / "inbox.json")
            subprocess.run(
                [sys.executable, script,
                 "--existing", local["existing"],
                 "--final-bank", local["final_bank"],
                 "--hot-green", local["hot_green"],
                 "--hot-review", local["hot_review"],
                 "--out", out, "--max-items", "60"],
                check=True,
            )
            return json.loads(Path(out).read_text(encoding="utf-8"))

    return publish(
        repo, "control/gpt_supergreen_inbox.json", branch, token, builder,
        f"inbox: direct live DCE {run_id} shard {shard}", attempts,
    )

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--shard", required=True)
    ap.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    ap.add_argument("--branch", default="main")
    ap.add_argument("--path", default="control/supergreen_hot.json")
    ap.add_argument("--review-path", default="control/gpt_review_hot.json")
    ap.add_argument("--max-green", type=int, default=200)
    ap.add_argument("--max-review", type=int, default=40)
    ap.add_argument("--attempts", type=int, default=12)
    ap.add_argument("--out", default="supergreen_hot_candidate.json")
    args = ap.parse_args()

    rows = load_records(args.review)
    ts = utc_now()
    greens = [compact_green(r, args.run_id, args.shard, ts) for r in rows if str(r.get("classification") or "").upper() in GREEN_CLASSES]
    reviews = [compact_review(r, args.run_id, args.shard, ts) for r in rows if str(r.get("classification") or "").upper() == REVIEW_CLASS and r.get("gate_readiness") and r.get("gate_evidence_candidates")]
    resolved = {item_key(r) for r in rows if str(r.get("classification") or "").upper() != REVIEW_CLASS}
    token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not args.repo or not token:
        raise SystemExit("GITHUB_REPOSITORY/GH_TOKEN required for hot publication")

    result = {"green_delta": len(greens), "review_delta": len(reviews), "green": None, "gpt_review": None, "inbox": None}
    if greens:
        result["green"] = publish(args.repo, args.path, args.branch, token, lambda e: merge_green(e, greens, args.run_id, args.shard, args.max_green), f"tender: hot green DCE {args.run_id} shard {args.shard}", args.attempts)
    if reviews or resolved:
        result["gpt_review"] = publish(args.repo, args.review_path, args.branch, token, lambda e: merge_review(e, reviews, resolved, args.run_id, args.shard, args.max_review), f"tender: GPT-ready DCE bank {args.run_id} shard {args.shard}", args.attempts)

    # The user-facing inbox is now rebuilt in this same shard. This is the primary
    # live path; the workflow-dispatched refresher can lag under runner saturation
    # without delaying control/gpt_supergreen_inbox.json anymore.
    try:
        result["inbox"] = publish_live_inbox(args.repo, args.branch, token, args.run_id, args.shard, args.attempts)
    except Exception as exc:
        # Preserve the authoritative DCE shard if GitHub content contention is
        # pathological; the existing dispatched refresh remains the fallback.
        result["inbox_error"] = str(exc)
        print(f"direct inbox publish fallback required: {exc}")

    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"published": bool(result["green"] or result["gpt_review"] or result["inbox"]), "green_delta": len(greens), "review_delta": len(reviews), "gpt_review_path": args.review_path if result["gpt_review"] else None, "direct_inbox": bool(result["inbox"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
