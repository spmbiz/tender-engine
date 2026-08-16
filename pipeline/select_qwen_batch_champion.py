#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "QWEN_BATCH_AUTOTUNE_CHAMPION_V1"


def load_candidates(root: Path) -> list[dict[str, Any]]:
    out = []
    for p in root.rglob("candidate.json"):
        try:
            x = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(x, dict):
            x["_path"] = str(p)
            out.append(x)
    return out


def viability(x: dict[str, Any]) -> tuple[int, float, int]:
    summary = x.get("summary") or {}
    golden = x.get("golden") or {}
    conserved = bool(summary.get("row_conservation_pass"))
    recall_pass = golden.get("scale_out_gate") == "PASS"
    singleton = int(summary.get("singleton_fallbacks") or 0)
    parse_rows = int(summary.get("parse_or_fallback_rows") or 0)
    splits = int(summary.get("split_events") or 0)
    rate = float(summary.get("notices_per_second") or 0.0)
    batch = int(summary.get("initial_batch_size") or x.get("batch_size") or 0)
    if not conserved or not recall_pass or singleton or parse_rows:
        tier = 0
    elif splits == 0:
        tier = 2
    else:
        tier = 1
    return tier, rate, batch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ledger-generation", default="UNKNOWN")
    args = ap.parse_args()

    candidates = load_candidates(Path(args.root))
    ranked = sorted(candidates, key=viability, reverse=True)
    eligible = [x for x in ranked if viability(x)[0] > 0]
    champion = eligible[0] if eligible else None
    payload = {
        "schema": SCHEMA,
        "workflow_run_id": args.run_id,
        "ledger_generation": args.ledger_generation,
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "status": "PASS" if champion else "BLOCKED",
        "selection_policy": {
            "tier_2": "golden PASS + row conservation + zero fallback rows + zero split events",
            "tier_1": "same hard gates but recovered through recursive splitting",
            "ordering": "tier desc, observed notices_per_second desc, initial batch size desc",
            "automatic_rejection_enabled": False,
        },
        "champion": None,
        "candidates": [],
    }
    for x in ranked:
        tier, rate, batch = viability(x)
        summary = x.get("summary") or {}
        golden = x.get("golden") or {}
        payload["candidates"].append({
            "batch_size": batch,
            "tier": tier,
            "notices_per_second": rate,
            "seconds_per_notice": summary.get("seconds_per_notice"),
            "split_events": summary.get("split_events"),
            "singleton_fallbacks": summary.get("singleton_fallbacks"),
            "parse_or_fallback_rows": summary.get("parse_or_fallback_rows"),
            "row_conservation_pass": summary.get("row_conservation_pass"),
            "golden_gate": golden.get("scale_out_gate"),
            "golden_recall": golden.get("known_positive_recall"),
            "golden_failures": golden.get("failures") or [],
            "artifact_path": x.get("_path"),
        })
    if champion:
        tier, rate, batch = viability(champion)
        s = champion.get("summary") or {}
        g = champion.get("golden") or {}
        payload["champion"] = {
            "initial_batch_size": batch,
            "tier": tier,
            "observed_notices_per_second": rate,
            "seconds_per_notice": s.get("seconds_per_notice"),
            "split_events": s.get("split_events"),
            "effective_batch_size_counts": s.get("effective_batch_size_counts"),
            "golden_known_positive_recall": g.get("known_positive_recall"),
            "classifier_version": s.get("classifier_version"),
            "classifier_prompt_version": s.get("classifier_prompt_version"),
            "safe_for_shadow_scale_out": True,
            "automatic_final_rejection": False,
        }

    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not champion:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
