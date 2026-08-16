from __future__ import annotations

"""Build a cumulative, compact GPT review reservoir from durable DCE releases.

The per-shard hot bank answers "what became ready this minute?". This backlog
answers "what authoritative, still-open DCE evidence have we already paid to
retrieve and still want ChatGPT to review?". It never upgrades eligibility and
never turns UNKNOWN into PASS.
"""

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from publish_supergreen_hot import spm_post_dce_rank

SCHEMA = "GPT_REVIEW_BACKLOG_V1"
DEFAULT_MAX_ITEMS = 120
DEFAULT_PORTAL_SHARE = 0.40
EVIDENCE_CHARS = 420
EVIDENCE_PER_GATE = 1


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def item_key(row: dict[str, Any]) -> str:
    cid = str(row.get("candidate_id") or "").strip().casefold()
    if cid:
        return cid
    return "|".join(str(row.get(k) or "").strip().casefold() for k in ("title", "buyer", "notice_url"))


def deadline_open(row: dict[str, Any]) -> bool:
    raw = str(row.get("deadline") or "").strip()
    if not raw:
        return True
    try:
        return date.fromisoformat(raw[:10]) >= datetime.now(timezone.utc).date()
    except Exception:
        return True


def compact_evidence(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalize all evidence shapes emitted by current and legacy DCE stages.

    aggregate_dce.py stores extracted gate candidates as {snippet, match, ...};
    the ChatGPT hot publisher uses {text, source}. Accept both without weakening
    authority/relevance gates.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for gate, values in raw.items():
        if not isinstance(values, list) or not values:
            continue
        kept: list[dict[str, Any]] = []
        for value in values[:EVIDENCE_PER_GATE]:
            if isinstance(value, dict):
                text = str(
                    value.get("text")
                    or value.get("snippet")
                    or value.get("context")
                    or ""
                ).strip()
                if not text:
                    continue
                kept.append({
                    "text": text[:EVIDENCE_CHARS],
                    "source": value.get("source") or value.get("file") or value.get("path"),
                })
            elif isinstance(value, str) and value.strip():
                kept.append({"text": value.strip()[:EVIDENCE_CHARS], "source": None})
        if kept:
            out[str(gate)] = kept
    return out


def compact_row(row: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    if not bool(row.get("gate_readiness")):
        return None
    relevance = row.get("candidate_document_relevance") or {}
    if isinstance(relevance, dict) and relevance and not bool(relevance.get("proven")):
        return None

    evidence = compact_evidence(
        row.get("gate_evidence_candidates")
        or row.get("gate_snippets")
        or row.get("evidence_by_gate")
        or {}
    )
    if not evidence:
        return None

    authority = row.get("authority_conflicts") or {}
    deadline_authority = authority.get("deadline") if isinstance(authority, dict) else {}
    deadline_authority = deadline_authority if isinstance(deadline_authority, dict) else {}

    compact = {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title"),
        "buyer": row.get("buyer"),
        "portal": str(row.get("portal") or "UNKNOWN").upper(),
        "notice_url": row.get("notice_url"),
        "deadline": row.get("deadline"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "preliminary_score": row.get("preliminary_score"),
        "content_quality": row.get("content_quality"),
        "gate_readiness": True,
        "candidate_document_relevance": {
            "status": relevance.get("status") if isinstance(relevance, dict) else None,
            "proven": bool(relevance.get("proven")) if isinstance(relevance, dict) else True,
        },
        "deadline_authority_status": deadline_authority.get("status"),
        "deadline_resolved": bool(
            deadline_authority.get("status") in {
                "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE",
                "DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING",
            }
            and not deadline_authority.get("conflict")
        ),
        "evidence_gate_coverage": len(evidence),
        "evidence_by_gate": evidence,
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "source_artifact": f"dce-deep-review-{run_id}.tar.gz",
        "review_contract": (
            "Authoritative candidate-linked DCE evidence only. This backlog is a review reservoir, "
            "not a verdict. Unknown is never PASS; FINAL_SUPER_GREEN still requires every mandatory gate."
        ),
    }
    score, band, reasons, blockers = spm_post_dce_rank(compact)
    compact["spm_post_dce_score"] = score
    compact["spm_fit_band"] = band
    compact["spm_fit_reasons"] = reasons
    compact["spm_friction_signals"] = blockers
    return compact


def quality_key(row: dict[str, Any]) -> tuple:
    return (
        int(row.get("spm_post_dce_score") or -100),
        bool(row.get("deadline_resolved")),
        int(row.get("evidence_gate_coverage") or 0),
        int(row.get("source_dce_run_id") or 0) if str(row.get("source_dce_run_id") or "").isdigit() else 0,
    )


def evidence_key(row: dict[str, Any]) -> tuple:
    return (
        int(row.get("evidence_gate_coverage") or 0),
        bool(row.get("deadline_resolved")),
        int(row.get("spm_post_dce_score") or -100),
    )


def portfolio_select(rows: list[dict[str, Any]], limit: int, portal_share: float) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    rows = [dict(r) for r in rows if deadline_open(r)]
    if not rows:
        return []

    priority_target = max(1, int(round(limit * 0.70)))
    diversity_target = max(1, int(round(limit * 0.20)))
    explore_target = max(0, limit - priority_target - diversity_target)
    cap = max(8, math.ceil(limit * max(0.20, min(0.80, portal_share))))

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts: Counter[str] = Counter()

    def emit(row: dict[str, Any], lane: str) -> bool:
        key = item_key(row)
        if not key or key in seen:
            return False
        portal = str(row.get("portal") or "UNKNOWN").upper()
        row = dict(row)
        row["review_lane"] = lane
        selected.append(row)
        seen.add(key)
        counts[portal] += 1
        return True

    ranked = sorted(rows, key=quality_key, reverse=True)
    for row in ranked:
        if len(selected) >= priority_target:
            break
        portal = str(row.get("portal") or "UNKNOWN").upper()
        if counts[portal] >= cap:
            continue
        emit(row, "SPM_PRIORITY")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ranked:
        if item_key(row) not in seen:
            grouped[str(row.get("portal") or "UNKNOWN").upper()].append(row)
    active = sorted(grouped, key=lambda p: (-quality_key(grouped[p][0])[0], p))
    diversity_absolute = min(limit, len(selected) + diversity_target)
    while active and len(selected) < diversity_absolute:
        nxt: list[str] = []
        for portal in active:
            if len(selected) >= diversity_absolute:
                break
            queue = grouped[portal]
            while queue:
                row = queue.pop(0)
                if emit(row, "PORTAL_DIVERSITY"):
                    break
            if queue:
                nxt.append(portal)
        active = nxt

    for row in sorted(rows, key=evidence_key, reverse=True):
        if len(selected) >= min(limit, diversity_absolute + explore_target):
            break
        emit(row, "EVIDENCE_EXPLORATION")

    for row in ranked:
        if len(selected) >= limit:
            break
        emit(row, "ELASTIC_RECALL")
    return selected[:limit]


def parse_input_spec(spec: str) -> tuple[str, Path]:
    if ":" not in spec:
        raise ValueError(f"--input must be RUN_ID:path, got {spec!r}")
    rid, path = spec.split(":", 1)
    rid = rid.strip()
    if not rid:
        raise ValueError(f"missing run id in {spec!r}")
    return rid, Path(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", default=[], help="RUN_ID:path/to/deep_review_queue.jsonl")
    ap.add_argument("--existing", default="control/gpt_review_backlog.json")
    ap.add_argument("--out", default="control/gpt_review_backlog.json")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("--max-portal-share", type=float, default=DEFAULT_PORTAL_SHARE)
    args = ap.parse_args()

    existing = load_json(Path(args.existing), {})
    merged: dict[str, dict[str, Any]] = {}
    for row in existing.get("items") or []:
        if isinstance(row, dict) and deadline_open(row):
            merged[item_key(row)] = row

    source_runs = [str(x) for x in (existing.get("source_dce_runs") or []) if str(x).strip()]
    added_by_run: dict[str, int] = {}
    for spec in args.input:
        run_id, path = parse_input_spec(spec)
        added = 0
        for row in load_jsonl(path):
            compact = compact_row(row, run_id)
            if compact is None or not deadline_open(compact):
                continue
            key = item_key(compact)
            current = merged.get(key)
            if current is None or quality_key(compact) >= quality_key(current):
                merged[key] = compact
                added += 1
        if run_id not in source_runs:
            source_runs.append(run_id)
        added_by_run[run_id] = added

    items = portfolio_select(list(merged.values()), args.max_items, args.max_portal_share)
    payload = {
        "schema": SCHEMA,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "source_dce_runs": source_runs[-80:],
        "source_run_additions": added_by_run,
        "portal_counts": dict(Counter(str(x.get("portal") or "UNKNOWN") for x in items)),
        "fit_band_counts": dict(Counter(str(x.get("spm_fit_band") or "UNKNOWN") for x in items)),
        "lane_counts": dict(Counter(str(x.get("review_lane") or "UNKNOWN") for x in items)),
        "items": items,
        "instruction": (
            "Persistent cross-generation DCE review reservoir. Review SPM_PRIORITY HOT/GOOD first, "
            "then PORTAL_DIVERSITY and EVIDENCE_EXPLORATION. This is not a final verdict. Unknown is never PASS."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": SCHEMA,
        "count": len(items),
        "added_by_run": added_by_run,
        "portal_counts": payload["portal_counts"],
        "fit_band_counts": payload["fit_band_counts"],
        "lane_counts": payload["lane_counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
