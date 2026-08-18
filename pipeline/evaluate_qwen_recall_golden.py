#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RANK = {"REJECT_OBVIOUS": 0, "MAYBE": 1, "FIT": 2, "STRONG_FIT": 3}
DEFAULT_MIN_CASES = 500
DEFAULT_MIN_POSITIVES = 100


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cid = str(row.get("canonical_notice_id") or row.get("id") or "").strip()
            if cid:
                out[cid] = row
    return out


def normalized_fields(row: dict[str, Any]) -> tuple[str, str]:
    classification = str(row.get("classification") or row.get("decision") or "").upper()
    mode = str(row.get("delivery_mode") or row.get("possible_delivery_route") or "").upper()
    return classification, mode


def evaluate(
    golden: dict[str, Any],
    rows: dict[str, dict[str, Any]],
    *,
    min_cases: int = DEFAULT_MIN_CASES,
    min_positives: int = DEFAULT_MIN_POSITIVES,
) -> dict[str, Any]:
    cases_out: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []
    positive_total = 0
    positive_retained = 0

    for case in golden.get("cases", []):
        cid = str(case["candidate_id"])
        expected = case.get("expected") or {}
        row = rows.get(cid)
        checks: list[dict[str, Any]] = []
        case_warnings: list[dict[str, Any]] = []
        passed = True
        if row is None:
            failures.append(f"missing_result:{cid}")
            cases_out.append({"candidate_id": cid, "label": case.get("label"), "passed": False, "checks": [{"check": "present", "passed": False}]})
            continue

        classification, mode = normalized_fields(row)
        lean = str(row.get("lean_attractiveness") or "UNKNOWN").upper()
        friction = [str(x).upper() for x in (row.get("friction_flags") or [])]

        if expected.get("must_not_reject"):
            positive_total += 1
            ok = classification != "REJECT_OBVIOUS"
            positive_retained += int(ok)
            checks.append({"check": "must_not_reject", "passed": ok, "actual": classification})
            passed &= ok
        if "min_rank" in expected:
            ok = RANK.get(classification, -1) >= RANK[str(expected["min_rank"])]
            checks.append({"check": "min_rank", "expected": expected["min_rank"], "actual": classification, "passed": ok})
            passed &= ok
        if "max_rank" in expected:
            ok = RANK.get(classification, 99) <= RANK[str(expected["max_rank"])]
            checks.append({"check": "max_rank", "expected": expected["max_rank"], "actual": classification, "passed": ok})
            passed &= ok
        if "exact_rank" in expected:
            ok = classification == str(expected["exact_rank"])
            checks.append({"check": "exact_rank", "expected": expected["exact_rank"], "actual": classification, "passed": ok})
            passed &= ok
        if "allowed_ranks" in expected:
            allowed = [str(x) for x in expected["allowed_ranks"]]
            ok = classification in allowed
            checks.append({"check": "allowed_ranks", "expected": allowed, "actual": classification, "passed": ok})
            passed &= ok
        if "allowed_modes" in expected:
            allowed_modes = [str(x) for x in expected["allowed_modes"]]
            ok = mode in allowed_modes
            checks.append({"check": "allowed_modes", "expected": allowed_modes, "actual": mode, "passed": ok})
            passed &= ok
        if "preferred_modes" in expected:
            preferred = [str(x) for x in expected["preferred_modes"]]
            ok = mode in preferred
            item = {"check": "preferred_modes", "expected": preferred, "actual": mode, "passed": ok, "severity": "warning"}
            case_warnings.append(item)
            if not ok:
                warnings.append(f"preferred_mode_mismatch:{cid}:{mode}")
        if "allowed_lean" in expected:
            allowed_lean = [str(x) for x in expected["allowed_lean"]]
            ok = lean in allowed_lean
            checks.append({"check": "allowed_lean", "expected": allowed_lean, "actual": lean, "passed": ok})
            passed &= ok
        if "required_friction_any" in expected:
            required = [str(x) for x in expected["required_friction_any"]]
            hits = sorted(set(required) & set(friction))
            ok = bool(hits)
            checks.append({"check": "required_friction_any", "expected": required, "actual": friction, "hits": hits, "passed": ok})
            passed &= ok

        if not passed:
            failures.append(f"policy_failure:{cid}")
        cases_out.append({
            "candidate_id": cid,
            "label": case.get("label"),
            "classification": classification,
            "delivery_mode": mode,
            "lean_attractiveness": lean,
            "friction_flags": friction,
            "model_classification": row.get("model_classification"),
            "model_delivery_mode": row.get("model_delivery_mode"),
            "passed": bool(passed),
            "checks": checks,
            "warnings": case_warnings,
        })

    recall = positive_retained / positive_total if positive_total else None
    case_count = len(golden.get("cases", []))
    corpus_failures = []
    if case_count < max(1, int(min_cases)):
        corpus_failures.append(f"insufficient_truth_cases:{case_count}<{int(min_cases)}")
    if positive_total < max(1, int(min_positives)):
        corpus_failures.append(f"insufficient_positive_recall_cases:{positive_total}<{int(min_positives)}")
    all_failures = failures + corpus_failures
    gate = "PASS" if not all_failures and recall == 1.0 else "BLOCK"
    return {
        "schema": "QWEN_RECALL_GOLDEN_REPORT_V4_CORPUS_GATE",
        "golden_schema": golden.get("schema"),
        "case_count": case_count,
        "cases_passed": sum(1 for c in cases_out if c["passed"]),
        "cases_failed": sum(1 for c in cases_out if not c["passed"]),
        "known_positive_recall": recall,
        "known_positive_retained": positive_retained,
        "known_positive_total": positive_total,
        "minimum_truth_cases_required": int(min_cases),
        "minimum_positive_recall_cases_required": int(min_positives),
        "corpus_ready": not corpus_failures,
        "quality_warning_count": len(warnings),
        "quality_warnings": warnings,
        "scale_out_gate": gate,
        "failures": all_failures,
        "policy": "A tiny perfect benchmark cannot unlock destructive or high-trust filtering. Scale-out PASS requires the configured substantial DCE/GPT-grounded corpus and zero known-positive recall misses.",
        "cases": cases_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--min-cases", type=int, default=DEFAULT_MIN_CASES)
    ap.add_argument("--min-positives", type=int, default=DEFAULT_MIN_POSITIVES)
    args = ap.parse_args()
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    report = evaluate(golden, load_jsonl(Path(args.results)), min_cases=args.min_cases, min_positives=args.min_positives)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["scale_out_gate"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
