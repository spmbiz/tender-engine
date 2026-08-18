from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from publish_supergreen_hot import compact_review, deadline_open, ensure_review_rank, item_key, review_sort
from rebuild_gpt_review_bank_from_release import load_json, load_jsonl, reviewable_authenticity, run_and_shard, source_version
from refresh_gpt_inbox_live import is_reviewed, ledger_ticks


def candidate_key(row: dict[str, Any]) -> str:
    return str(row.get("candidate_id") or "").strip().casefold()


def compact_index_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep enough metadata to locate/re-rank every reviewable DCE without huge evidence blobs."""
    ranked = ensure_review_rank(row)
    locator = ranked.get("artifact_locator") if isinstance(ranked.get("artifact_locator"), dict) else {}
    return {
        "candidate_id": ranked.get("candidate_id"),
        "title": ranked.get("title"),
        "buyer": ranked.get("buyer"),
        "portal": ranked.get("portal"),
        "notice_url": ranked.get("notice_url"),
        "deadline": ranked.get("deadline"),
        "estimated_value": ranked.get("estimated_value"),
        "currency": ranked.get("currency"),
        "review_stage": ranked.get("review_stage") or "BUSINESS_GATES",
        "gate_readiness": bool(ranked.get("gate_readiness")),
        "content_quality": ranked.get("content_quality"),
        "deadline_resolved": bool(ranked.get("deadline_resolved")),
        "deadline_authority_status": ranked.get("deadline_authority_status"),
        "evidence_gate_coverage": int(ranked.get("evidence_gate_coverage") or 0),
        "priority_score": int(ranked.get("priority_score") or ranked.get("preliminary_score") or 0),
        "spm_post_dce_score": int(ranked.get("spm_post_dce_score") or 0),
        "spm_fit_band": ranked.get("spm_fit_band"),
        "spm_fit_reasons": ranked.get("spm_fit_reasons") or [],
        "spm_friction_signals": ranked.get("spm_friction_signals") or [],
        "source_dce_run_id": ranked.get("source_dce_run_id"),
        "source_shard": ranked.get("source_shard"),
        "artifact_locator": {
            "dce_run_id": ranked.get("source_dce_run_id") or locator.get("dce_run_id"),
            "shard": ranked.get("source_shard") if ranked.get("source_shard") is not None else locator.get("shard"),
            "candidate_id": ranked.get("candidate_id"),
            "release_tag": locator.get("release_tag") or (f"dce-harvest-{ranked.get('source_dce_run_id')}" if ranked.get("source_dce_run_id") else None),
        },
        "hot_ready_at": ranked.get("hot_ready_at"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-root", required=True)
    ap.add_argument("--existing", required=True)
    ap.add_argument("--final-bank", required=True)
    ap.add_argument("--review-ledger", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    existing = load_json(Path(args.existing), {})
    final_bank = load_json(Path(args.final_bank), {})
    review_ledger = load_json(Path(args.review_ledger), {})
    ticks = ledger_ticks(review_ledger)
    final_ids = {
        candidate_key(x) for x in (final_bank.get("items") or [])
        if isinstance(x, dict) and candidate_key(x)
    }

    merged: dict[str, dict[str, Any]] = {}
    for row in existing.get("items") or []:
        if not isinstance(row, dict) or not candidate_key(row) or not deadline_open(row):
            continue
        if candidate_key(row) in final_ids or is_reviewed(row, ticks):
            continue
        merged[candidate_key(row)] = compact_index_row(row)

    scanned = 0
    gate_rows = 0
    auth_rows = 0
    source_runs: set[int] = set()
    shard_files = sorted(Path(args.release_root).rglob("fast-adjudication-shard-*.jsonl"))
    for path in shard_files:
        run_id, shard = run_and_shard(path)
        if run_id:
            source_runs.add(run_id)
        for raw in load_jsonl(path):
            scanned += 1
            classification = str(raw.get("classification") or "").upper()
            is_gate = classification == "MODEL_REVIEW_REQUIRED" and bool(raw.get("gate_readiness"))
            is_auth = classification == "YELLOW" and reviewable_authenticity(raw)
            if not (is_gate or is_auth):
                continue
            gate_rows += int(is_gate)
            auth_rows += int(is_auth)
            compact = compact_review(raw, str(run_id or 0), str(shard), datetime.now(timezone.utc).isoformat())
            compact["review_stage"] = "BUSINESS_GATES" if is_gate else "DCE_AUTHENTICITY"
            compact["dce_authenticity_review_required"] = bool(is_auth)
            compact["artifact_locator"] = {
                "dce_run_id": run_id,
                "shard": shard,
                "candidate_id": raw.get("candidate_id"),
                "release_tag": f"dce-harvest-{run_id}" if run_id else None,
            }
            k = candidate_key(compact)
            if not k or k in final_ids or is_reviewed(compact, ticks) or not deadline_open(compact):
                continue
            indexed = compact_index_row(compact)
            cur = merged.get(k)
            if cur is None or source_version(indexed) >= source_version(cur):
                merged[k] = indexed

    items = list(merged.values())
    # Quality/actability first. Newer generation is only a tiebreaker; it must not
    # evict a stronger older unreviewed DCE from the user-facing review universe.
    items.sort(key=lambda r: (review_sort(r), int(r.get("source_dce_run_id") or 0)), reverse=True)
    stage_counts = Counter(str(x.get("review_stage") or "UNKNOWN") for x in items)
    band_counts = Counter(str(x.get("spm_fit_band") or "UNKNOWN") for x in items)
    payload = {
        "schema": "GPT_REVIEW_INDEX_V1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
        "counts": {
            "pending_total_uncapped": len(items),
            "by_stage": dict(stage_counts),
            "by_spm_fit_band": dict(band_counts),
            "rich_hot_window_target": 160,
            "overflow_beyond_hot_160": max(0, len(items) - 160),
        },
        "recovery": {
            "shard_files_scanned_this_refresh": len(shard_files),
            "adjudication_rows_scanned_this_refresh": scanned,
            "gate_rows_seen_this_refresh": gate_rows,
            "authenticity_rows_seen_this_refresh": auth_rows,
            "source_runs_seen_this_refresh": sorted(source_runs, reverse=True),
        },
        "contract": "Uncapped durable directory of GPT Web work. Compact metadata only; authoritative evidence remains in the referenced DCE release/shard. Presence here is never a GREEN verdict.",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"count": len(items), "counts": payload["counts"], "recovery": payload["recovery"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
