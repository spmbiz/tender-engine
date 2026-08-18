from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_qwen_dce_selection import cid, mh, read_json, read_jsonl
from dce_attempt_ledger import load_attempt_index, was_attempted
from procurement_code_prior import code_priority


def _key(v: Any) -> str:
    return str(v or "").strip().casefold()


def _items(path: Path, field: str = "items") -> list[dict[str, Any]]:
    obj = read_json(path)
    rows = obj.get(field)
    return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []


def _final_ids(path: Path) -> set[str]:
    return {_key(x.get("candidate_id")) for x in _items(path) if _key(x.get("candidate_id"))}


def _inbox_ids(path: Path) -> set[str]:
    obj = read_json(path)
    rows = obj.get("review_queue") or obj.get("pending_final_review") or []
    return {_key(x.get("candidate_id")) for x in rows if isinstance(x, dict) and _key(x.get("candidate_id"))}


def _processed(path: Path) -> tuple[set[str], set[str]]:
    obj = read_json(path)
    permanent = {_key(x) for x in obj.get("processed_candidate_ids", []) if _key(x)}
    cooldown = set()
    raw = obj.get("dce_retry_after")
    if isinstance(raw, dict):
        cooldown = {_key(x) for x in raw if _key(x)}
    return permanent, cooldown


def _current_state(state: Path, ledger: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    led = {cid(x): x for x in read_jsonl(ledger) if cid(x)}
    rows = []
    for row in read_jsonl(state):
        c = cid(row)
        current = led.get(c)
        if not c or not current or mh(current) != mh(row):
            continue
        rows.append(row)
    return rows, led


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--controller-state", required=True)
    ap.add_argument("--attempt-ledger", required=True)
    ap.add_argument("--inbox", required=True)
    ap.add_argument("--final-bank", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    state_rows, ledger = _current_state(Path(args.state), Path(args.ledger))
    snapshot = {cid(x): x for x in read_jsonl(Path(args.snapshot)) if cid(x)}
    attempts = load_attempt_index(Path(args.attempt_ledger))
    processed, cooldown = _processed(Path(args.controller_state))
    inbox = _inbox_ids(Path(args.inbox))
    final = _final_ids(Path(args.final_bank))

    decisions = Counter()
    survival = Counter()
    modes = Counter()
    fit_funnel = Counter()
    all_funnel = Counter()
    decision_funnel: dict[str, Counter] = defaultdict(Counter)
    code_stats = Counter()
    contradiction_examples: list[dict[str, Any]] = []
    positive_maybe_examples: list[dict[str, Any]] = []

    for row in state_rows:
        c = cid(row)
        ck = _key(c)
        decision = str(row.get("classification") or "UNKNOWN").upper()
        keep = str(row.get("survival_decision") or "KEEP").upper()
        dce_eligible = bool(row.get("dce_eligible", True))
        decisions[decision] += 1
        survival[keep] += 1
        modes[str(row.get("delivery_mode") or "UNCLEAR").upper()] += 1

        snap = snapshot.get(c) or {}
        probe = {
            "candidate_id": c,
            "material_fields_hash": mh(row),
            "wide_read_run_id": snap.get("wide_read_run_id") or snap.get("source_discovery_run"),
        }
        attempted = was_attempted(probe, attempts)
        is_processed = ck in processed
        is_cooldown = ck in cooldown
        in_inbox = ck in inbox
        in_final = ck in final
        all_funnel["current_exact_hash_qwen"] += 1
        all_funnel["dce_attempted_exact_version"] += int(attempted)
        all_funnel["controller_processed"] += int(is_processed)
        all_funnel["retry_cooldown"] += int(is_cooldown)
        all_funnel["in_gpt_inbox"] += int(in_inbox)
        all_funnel["in_final_bank"] += int(in_final)

        df = decision_funnel[decision]
        df["current"] += 1
        df["keep"] += int(keep == "KEEP")
        df["dce_eligible"] += int(dce_eligible)
        df["dce_attempted_exact_version"] += int(attempted)
        df["controller_processed"] += int(is_processed)
        df["retry_cooldown"] += int(is_cooldown)
        df["in_gpt_inbox"] += int(in_inbox)
        df["in_final_bank"] += int(in_final)
        df["unattempted_unprocessed"] += int(not attempted and not is_processed and not is_cooldown)

        is_fit = decision in {"STRONG_FIT", "FIT"} and keep == "KEEP" and dce_eligible
        if is_fit:
            fit_funnel["qwen_fit_current"] += 1
            fit_funnel["dce_attempted_exact_version"] += int(attempted)
            fit_funnel["controller_processed"] += int(is_processed)
            fit_funnel["retry_cooldown"] += int(is_cooldown)
            fit_funnel["in_gpt_inbox"] += int(in_inbox)
            fit_funnel["in_final_bank"] += int(in_final)
            if not attempted and not is_processed and not is_cooldown:
                fit_funnel["unattempted_unblocked"] += 1
            if is_processed and not attempted:
                fit_funnel["processed_without_exact_attempt_record"] += 1
            if attempted and not is_processed and not is_cooldown and not in_inbox and not in_final:
                fit_funnel["attempted_not_visible_anywhere"] += 1

        prior = code_priority(snap)
        if prior["positive"]:
            code_stats["positive_code"] += 1
            decision_funnel[decision]["positive_procurement_code"] += 1
        if prior["contradiction"]:
            code_stats["noncore_cpv_contradiction"] += 1
            decision_funnel[decision]["noncore_cpv_contradiction"] += 1
            if is_fit and len(contradiction_examples) < 30:
                contradiction_examples.append({
                    "candidate_id": c,
                    "title": snap.get("title") or (snap.get("notice") or {}).get("title"),
                    "qwen_classification": decision,
                    "delivery_mode": row.get("delivery_mode"),
                    "codes": prior,
                    "attempted": attempted,
                    "processed": is_processed,
                    "in_inbox": in_inbox,
                })
        if decision == "MAYBE" and prior["delta"] > 0 and len(positive_maybe_examples) < 30:
            positive_maybe_examples.append({
                "candidate_id": c,
                "title": snap.get("title") or (snap.get("notice") or {}).get("title"),
                "qwen_classification": decision,
                "delivery_mode": row.get("delivery_mode"),
                "lean_attractiveness": row.get("lean_attractiveness"),
                "codes": prior,
                "attempted": attempted,
                "processed": is_processed,
                "in_inbox": in_inbox,
            })

    fit_total = int(fit_funnel.get("qwen_fit_current", 0))
    fit_covered = sum(
        1 for row in state_rows
        if str(row.get("classification") or "").upper() in {"STRONG_FIT", "FIT"}
        and str(row.get("survival_decision") or "KEEP").upper() == "KEEP"
        and bool(row.get("dce_eligible", True))
        and (
            was_attempted({
                "candidate_id": cid(row),
                "material_fields_hash": mh(row),
                "wide_read_run_id": (snapshot.get(cid(row)) or {}).get("wide_read_run_id") or (snapshot.get(cid(row)) or {}).get("source_discovery_run"),
            }, attempts)
            or _key(cid(row)) in processed
            or _key(cid(row)) in cooldown
            or _key(cid(row)) in inbox
            or _key(cid(row)) in final
        )
    )

    payload = {
        "schema": "QWEN_DCE_FUNNEL_AUDIT_V2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state_current_exact_hash_rows": len(state_rows),
        "ledger_rows": len(ledger),
        "snapshot_rows": len(snapshot),
        "decision_counts": dict(decisions),
        "survival_counts": dict(survival),
        "delivery_mode_counts": dict(modes),
        "all_current_qwen_funnel": dict(all_funnel),
        "decision_funnel": {k: dict(v) for k, v in decision_funnel.items()},
        "fit_funnel": dict(fit_funnel),
        "fit_coverage": {
            "qwen_fit_current": fit_total,
            "covered_by_attempt_processed_cooldown_inbox_or_final": fit_covered,
            "coverage_fraction": round(fit_covered / fit_total, 6) if fit_total else 1.0,
            "hard_invariant": "Every current KEEP+dce_eligible STRONG_FIT/FIT must either have DCE progress evidence or remain explicitly unattempted/unblocked; no silent disappearance.",
        },
        "code_prior_audit": dict(code_stats),
        "qwen_fit_noncore_code_contradiction_examples": contradiction_examples,
        "qwen_maybe_positive_code_examples": positive_maybe_examples,
        "safety": {
            "exact_material_hash_checked": True,
            "code_prior_is_observability_only_here": True,
            "no_classification_or_eligibility_mutation": True,
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
