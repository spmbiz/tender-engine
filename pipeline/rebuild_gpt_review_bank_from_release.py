from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from post_dce_scope_gate import evaluate_post_dce_scope
from publish_supergreen_hot import (
    compact_review,
    deadline_open,
    ensure_review_rank,
    item_key,
    review_sort,
)

KNOWN_NON_DCE_QUALITY = {
    "ACCESS_GUIDE_ONLY",
    "PORTAL_GENERIC_ONLY",
    "NOTICE_ONLY",
    "EXTRACTION_EMPTY",
    "NOT_APPLICABLE",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def run_and_shard(path: Path) -> tuple[int, int]:
    run_id = 0
    for part in path.parts:
        m = re.fullmatch(r"(?:dce-harvest-)?(\d{8,})", part)
        if m:
            run_id = max(run_id, as_int(m.group(1)))
    sm = re.search(r"fast-adjudication-shard-(\d+)\.jsonl$", path.name)
    return run_id, as_int(sm.group(1) if sm else 0)


def reviewable_authenticity(row: dict[str, Any]) -> bool:
    """Allow GPT Web to inspect retrieved material without pretending it is gate-ready.

    This is a review-surface decision only. It never upgrades evidence quality and it
    never authorizes finalization. Known portal guides / notice-only / empty extracts
    stay out of the inbox.
    """
    quality = str(row.get("content_quality") or "").upper()
    evidence = row.get("evidence_quality") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    ev_quality = str(evidence.get("content_quality") or quality).upper()
    raw_status = str(evidence.get("raw_status") or "").upper()
    text_chars = as_int(evidence.get("text_chars"))
    docs_with_text = as_int(evidence.get("documents_with_text"))

    if quality in KNOWN_NON_DCE_QUALITY or ev_quality in KNOWN_NON_DCE_QUALITY:
        return False
    if raw_status != "DOWNLOADED_PUBLIC":
        return False
    if docs_with_text < 1 or text_chars < 1000:
        return False
    return quality in {
        "UNKNOWN_RETRIEVED_DOCUMENT",
        "SUBSTANTIVE_DCE_RELEVANCE_UNVERIFIED",
        "SUBSTANTIVE_DCE_PRESENT",
        "MIXED_SUBSTANTIVE_AND_GUIDE",
    } or ev_quality in {
        "UNKNOWN_RETRIEVED_DOCUMENT",
        "SUBSTANTIVE_DCE_PRESENT",
        "MIXED_SUBSTANTIVE_AND_GUIDE",
    }


def source_version(row: dict[str, Any]) -> tuple[int, int, int, int, str]:
    return (
        as_int(row.get("source_dce_run_id")),
        int(bool(row.get("gate_readiness"))),
        int(row.get("evidence_gate_coverage") or 0),
        int(row.get("priority_score") or row.get("preliminary_score") or 0),
        str(row.get("hot_ready_at") or ""),
    )


def _business_gate_scope_reject(row: dict[str, Any]) -> dict[str, Any] | None:
    stage = str(row.get("review_stage") or "BUSINESS_GATES").upper()
    if stage == "DCE_AUTHENTICITY" or not bool(row.get("gate_readiness")):
        return None
    result = evaluate_post_dce_scope(row)
    return result if result.get("auto_reject") else None


def _count_scope_reject(result: dict[str, Any], reason_counts: dict[str, int]) -> None:
    for reason in result.get("reason_codes") or []:
        key = str(reason)
        reason_counts[key] = reason_counts.get(key, 0) + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", required=True)
    ap.add_argument("--existing", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-items", type=int, default=160)
    args = ap.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    merged: dict[str, dict[str, Any]] = {}
    scope_auto_rejected = 0
    scope_reason_counts: dict[str, int] = {}
    existing = load_json(Path(args.existing), {})
    if isinstance(existing, dict):
        for row in existing.get("items") or []:
            if not isinstance(row, dict) or not deadline_open(row):
                continue
            scope_result = _business_gate_scope_reject(row)
            if scope_result:
                scope_auto_rejected += 1
                _count_scope_reject(scope_result, scope_reason_counts)
                continue
            ranked = ensure_review_rank(row)
            merged[item_key(ranked)] = ranked

    shard_files = sorted(Path(args.release_root).rglob("fast-adjudication-shard-*.jsonl"))
    source_runs: set[int] = set()
    scanned_rows = 0
    model_review_rows = 0
    authenticity_rows = 0

    for path in shard_files:
        run_id, shard = run_and_shard(path)
        if run_id:
            source_runs.add(run_id)
        for raw in load_jsonl(path):
            scanned_rows += 1
            classification = str(raw.get("classification") or "").upper()
            is_gate_review = classification == "MODEL_REVIEW_REQUIRED"
            is_auth_review = classification == "YELLOW" and reviewable_authenticity(raw)
            if not (is_gate_review or is_auth_review):
                continue

            if is_gate_review:
                scope_result = evaluate_post_dce_scope(raw)
                if bool(raw.get("gate_readiness")) and scope_result.get("auto_reject"):
                    scope_auto_rejected += 1
                    _count_scope_reject(scope_result, scope_reason_counts)
                    continue

            compact = compact_review(raw, str(run_id or 0), str(shard), now)
            compact["upstream_classification"] = classification
            compact["review_stage"] = "BUSINESS_GATES" if is_gate_review else "DCE_AUTHENTICITY"
            compact["dce_authenticity_review_required"] = bool(is_auth_review)
            compact["finalization_allowed"] = False
            compact["artifact_locator"] = {
                "dce_run_id": run_id,
                "shard": shard,
                "candidate_id": raw.get("candidate_id"),
                "release_tag": f"dce-harvest-{run_id}" if run_id else None,
            }
            compact["evidence_quality_summary"] = raw.get("evidence_quality") or {}
            compact = ensure_review_rank(compact)
            if not deadline_open(compact):
                continue

            key = item_key(compact)
            cur = merged.get(key)
            if cur is None or source_version(compact) >= source_version(cur):
                merged[key] = compact
            model_review_rows += int(is_gate_review)
            authenticity_rows += int(is_auth_review)

    all_items = list(merged.values())
    # Rank the whole recovered universe by review usefulness first. Source recency
    # is only a tiebreaker; it must never evict a stronger older unreviewed DCE.
    all_items.sort(key=lambda r: (review_sort(r), source_version(r)[0]), reverse=True)
    uncapped_unique_pending = len(all_items)
    items = all_items[: max(0, args.max_items)]

    latest_run = max([as_int(existing.get("latest_dce_run_id"))] + list(source_runs) + [0])
    payload = {
        "schema": "GPT_REVIEW_HOT_V5",
        "updated_at": now,
        "latest_dce_run_id": latest_run or None,
        "generation_reset": False,
        "count": len(items),
        "items": items,
        "source_runs_recovered": sorted(source_runs, reverse=True),
        "recovery_metrics": {
            "shard_files_scanned": len(shard_files),
            "adjudication_rows_scanned": scanned_rows,
            "model_review_rows_seen": model_review_rows,
            "dce_authenticity_rows_seen": authenticity_rows,
            "scope_auto_rejected": scope_auto_rejected,
            "scope_auto_reject_reason_counts": scope_reason_counts,
            "uncapped_unique_pending_before_hot_window": uncapped_unique_pending,
            "rich_hot_window_count": len(items),
            "overflow_beyond_hot_window": max(0, uncapped_unique_pending - len(items)),
        },
        "ranking_contract": "Persistent GPT Web rich hot window. Global review usefulness is ranked before the cap; source-run recency is only a tiebreaker. The uncapped compact directory is control/gpt_review_index.json. BUSINESS_GATES rows have gate-ready DCE; DCE_AUTHENTICITY rows still require DCE relevance verification. Ranking is never eligibility truth.",
        "instruction": "GPT Web reviews this rich window directly. For overflow, consult control/gpt_review_index.json and follow artifact_locator to the authoritative DCE run/shard. Unknown is never PASS.",
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["recovery_metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
