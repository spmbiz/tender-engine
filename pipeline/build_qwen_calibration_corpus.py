#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POSITIVE_CLASSES = {"GREEN", "YELLOW", "FINAL_SUPER_GREEN", "SUPER_GREEN"}
TARGET_CASES = 500
TARGET_POSITIVES = 100


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def cid(row: dict[str, Any]) -> str:
    notice = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    return str(row.get("candidate_id") or row.get("canonical_notice_id") or notice.get("candidate_id") or "").strip()


def material_hash(notice: dict[str, Any]) -> str:
    keys = (
        "candidate_id", "source_family", "source", "country", "buyer", "title", "description",
        "cpv_or_category", "estimated_value", "currency", "publication_date", "deadline", "deadline_utc",
        "procedure", "lots", "notice_eligibility", "award_criteria", "subcontracting", "urls",
    )
    payload = {k: notice.get(k) for k in keys}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def envelope_from_notice(notice: dict[str, Any]) -> dict[str, Any]:
    candidate = cid(notice)
    return {
        "canonical_notice_id": candidate,
        "material_fields_hash": material_hash(notice),
        "notice": notice,
        "calibration_input_frozen_at": now_utc(),
    }


def existing_cases(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    payload = read_json(path)
    return {str(x.get("candidate_id") or ""): x for x in payload.get("cases", []) if isinstance(x, dict) and x.get("candidate_id")}


def manual_expected(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    payload = read_json(path)
    return {str(x.get("candidate_id") or ""): x for x in payload.get("cases", []) if isinstance(x, dict) and x.get("candidate_id")}


def adjudicated_truth(root: Path) -> dict[str, dict[str, Any]]:
    truth: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        obj = read_json(path)
        if obj.get("persist_to_final_bank") is not True:
            continue
        for row in obj.get("results", []) or []:
            if not isinstance(row, dict):
                continue
            candidate = cid(row)
            classification = str(row.get("classification") or "").upper()
            if not candidate or classification not in POSITIVE_CLASSES:
                continue
            truth[candidate] = {
                "classification": classification,
                "final_score": row.get("final_score"),
                "why": row.get("why"),
                "action": row.get("action"),
                "evidence_quality": row.get("evidence_quality"),
                "provenance_file": str(path),
                "adjudication_schema": obj.get("schema"),
            }
    return truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--adjudications", default="control/adjudications")
    ap.add_argument("--manual", default="benchmarks/qwen_recall_golden_v1.json")
    ap.add_argument("--existing", default="benchmarks/qwen_recall_golden_auto.json")
    ap.add_argument("--out", default="benchmarks/qwen_recall_golden_auto.json")
    ap.add_argument("--target-cases", type=int, default=TARGET_CASES)
    ap.add_argument("--target-positives", type=int, default=TARGET_POSITIVES)
    args = ap.parse_args()

    existing = existing_cases(Path(args.existing))
    manual = manual_expected(Path(args.manual))
    truth = adjudicated_truth(Path(args.adjudications))
    snapshot = {cid(row): row for row in iter_jsonl(Path(args.snapshot)) if cid(row)}

    wanted = set(manual) | set(truth) | set(existing)
    cases: list[dict[str, Any]] = []
    frozen = 0
    missing_input: list[str] = []
    positive_count = 0

    for candidate in sorted(wanted):
        old = existing.get(candidate) or {}
        input_envelope = old.get("input_envelope") if isinstance(old.get("input_envelope"), dict) else None
        if input_envelope is None and candidate in snapshot:
            input_envelope = envelope_from_notice(snapshot[candidate])
        if input_envelope is None:
            missing_input.append(candidate)
            continue
        frozen += 1

        adjudication = truth.get(candidate)
        seed = manual.get(candidate)
        if adjudication:
            positive_count += 1
            expected = {"must_not_reject": True, "min_rank": "MAYBE"}
            label = f"DCE/GPT positive ({adjudication['classification']}): {candidate}"
            truth_kind = "DCE_GPT_ADJUDICATED_POSITIVE"
        elif seed:
            expected = dict(seed.get("expected") or {})
            label = str(seed.get("label") or candidate)
            truth_kind = "MANUAL_POLICY_CONTROL"
            if expected.get("must_not_reject"):
                positive_count += 1
        else:
            # Existing frozen cases survive even if their source adjudication file
            # was later archived; do not silently discard durable calibration data.
            expected = dict(old.get("expected") or {})
            label = str(old.get("label") or candidate)
            truth_kind = str(old.get("truth_kind") or "FROZEN_EXISTING_CASE")
            if expected.get("must_not_reject"):
                positive_count += 1

        cases.append({
            "candidate_id": candidate,
            "label": label,
            "truth_kind": truth_kind,
            "expected": expected,
            "adjudication": adjudication,
            "input_envelope": input_envelope,
        })

    target_cases = max(1, int(args.target_cases))
    target_positives = max(1, int(args.target_positives))
    ready = len(cases) >= target_cases and positive_count >= target_positives
    payload = {
        "schema": "QWEN_RECALL_CALIBRATION_CORPUS_V1",
        "generated_at": now_utc(),
        "case_count": len(cases),
        "positive_recall_cases": positive_count,
        "frozen_input_cases": frozen,
        "missing_input_candidate_ids": missing_input,
        "targets": {"minimum_cases": target_cases, "minimum_positive_recall_cases": target_positives},
        "ready_for_destructive_filter_calibration": ready,
        "policy": "Only DCE/GPT adjudicated YELLOW/GREEN or explicit manual controls become semantic truth. RED DCE verdicts are not auto-labelled as notice-level rejects because bidder/gate failures may be invisible at notice stage. Frozen notice inputs preserve historical calibration after expiry.",
        "cases": cases,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("schema", "case_count", "positive_recall_cases", "frozen_input_cases", "targets", "ready_for_destructive_filter_calibration")}, indent=2))


if __name__ == "__main__":
    main()
