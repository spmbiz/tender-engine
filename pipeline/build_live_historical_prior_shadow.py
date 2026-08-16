#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from pipeline import historical_market_priors as historical

SCHEMA = "LIVE_HISTORICAL_PRIOR_SHADOW_V1"
SUMMARY_SCHEMA = "LIVE_HISTORICAL_PRIOR_SHADOW_SUMMARY_V1"


def _open_text(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with _open_text(path, "r") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def write_row(fh, row: dict[str, Any]) -> None:
    fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def notice_from_envelope(row: dict[str, Any]) -> dict[str, Any]:
    notice = row.get("notice")
    return notice if isinstance(notice, dict) else row


def candidate_id(row: dict[str, Any], notice: dict[str, Any]) -> str:
    return str(
        row.get("canonical_notice_id")
        or notice.get("candidate_id")
        or notice.get("notice_id")
        or notice.get("id")
        or ""
    ).strip()


def enrich(row: dict[str, Any], priors: dict[str, Any], source_run: str) -> dict[str, Any]:
    notice = notice_from_envelope(row)
    delta, reasons = historical.adjustment(notice, priors)
    out = dict(row)
    out["historical_prior"] = {
        "schema": SCHEMA,
        "source_run": source_run,
        "priority_adjustment": int(delta),
        "reasons": list(reasons),
        "prior_contract": priors.get("contract"),
        "prior_source_release": priors.get("source_release"),
        "pre_dce_only": True,
        "affects_final_verdict": False,
        "satisfies_dce_gates": False,
        "unknown_is_not_pass": True,
    }
    return out


def promoted_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    prior = row.get("historical_prior") or {}
    notice = notice_from_envelope(row)
    delta = int(prior.get("priority_adjustment") or 0)
    deadline = str(notice.get("deadline_utc") or notice.get("deadline") or "9999")
    return (-delta, deadline, candidate_id(row, notice))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Apply historical market priors to the live classification queue without dropping any notice."
    )
    ap.add_argument("--input", required=True, help="Notice classification queue JSONL(.gz)")
    ap.add_argument("--priors", default="control/historical_market_priors.json")
    ap.add_argument("--source-run", required=True)
    ap.add_argument("--all-out", required=True)
    ap.add_argument("--promoted-out", required=True)
    ap.add_argument("--residual-out", required=True)
    ap.add_argument("--summary-out", required=True)
    args = ap.parse_args()

    priors = historical.load(args.priors)
    if not priors:
        raise SystemExit(f"Historical priors are not READY: {args.priors}")

    input_path = Path(args.input)
    all_path = Path(args.all_out)
    promoted_path = Path(args.promoted_out)
    residual_path = Path(args.residual_out)
    summary_path = Path(args.summary_out)
    for p in (all_path, promoted_path, residual_path, summary_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    promoted: list[dict[str, Any]] = []
    total = 0
    residual = 0
    malformed_identity = 0
    bonus_counts: Counter[int] = Counter()
    source_counts: Counter[str] = Counter()

    with _open_text(all_path, "w") as all_fh, _open_text(residual_path, "w") as residual_fh:
        for row in read_jsonl(input_path):
            total += 1
            notice = notice_from_envelope(row)
            cid = candidate_id(row, notice)
            if not cid:
                malformed_identity += 1

            enriched = enrich(row, priors, args.source_run)
            prior = enriched["historical_prior"]
            delta = int(prior["priority_adjustment"])
            bonus_counts[delta] += 1
            source_counts[str(notice.get("source") or "UNKNOWN")] += 1
            write_row(all_fh, enriched)

            if delta > 0:
                promoted.append(enriched)
            else:
                # Residual means "not promoted by the current historical prior contract".
                # It is NOT a reject set and remains eligible for open-world/Qwen/GPT review.
                write_row(residual_fh, enriched)
                residual += 1

    promoted.sort(key=promoted_sort_key)
    with _open_text(promoted_path, "w") as promoted_fh:
        for row in promoted:
            write_row(promoted_fh, row)

    summary = {
        "schema": SUMMARY_SCHEMA,
        "source_run": str(args.source_run),
        "input_rows": total,
        "all_enriched_rows": total,
        "promoted_rows": len(promoted),
        "residual_rows": residual,
        "malformed_identity_rows": malformed_identity,
        "priority_adjustment_counts": {str(k): v for k, v in sorted(bonus_counts.items())},
        "source_counts": dict(sorted(source_counts.items())),
        "prior_contract": priors.get("contract"),
        "prior_source_release": priors.get("source_release"),
        "safety": {
            "raw_input_unchanged": True,
            "drops_or_deletes_notices": False,
            "residual_is_reject": False,
            "pre_dce_only": True,
            "affects_final_verdict": False,
            "satisfies_dce_gates": False,
            "unknown_is_not_pass": True,
        },
        "outputs": {
            "all": str(all_path),
            "promoted": str(promoted_path),
            "residual": str(residual_path),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
