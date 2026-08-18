from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_gpt_web_read_batches import GATES, clip
from rebuild_gpt_review_bank_from_release import load_jsonl, run_and_shard

# Keep the exhaustive surface small enough for the conversation assistant to read
# every candidate. These are evidence snippets only; no verdict is emitted here.
STRESS_GATES = (
    "entity_geography",
    "turnover_financial",
    "references_experience",
    "certifications_partner",
    "staffing_team",
    "insurance_bonds",
    "subcontracting_consortium",
    "deliverables_scope",
    "sla_onsite",
    "term_value",
    "award_criteria",
    "forms_signatures",
    "submission",
    "ip_data_security",
    "payment_tax",
)


def load(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def cid(row: dict[str, Any]) -> str:
    return str(row.get("candidate_id") or row.get("canonical_notice_id") or "").strip()


def key(value: Any) -> str:
    return str(value or "").strip().casefold()


def gate_evidence(row: dict[str, Any], chars: int = 360) -> dict[str, dict[str, Any]]:
    raw = row.get("evidence_by_gate") or row.get("gate_evidence_candidates") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for gate in STRESS_GATES:
        vals = raw.get(gate)
        if not isinstance(vals, list) or not vals:
            continue
        item = vals[0]
        if isinstance(item, dict):
            text = clip(item.get("text") or item.get("snippet") or item.get("context"), chars)
            source = item.get("source") or item.get("file") or item.get("path")
        else:
            text = clip(item, chars)
            source = None
        if text:
            out[gate] = {"text": text, "source": source}
    return out


def raw_quality(row: dict[str, Any]) -> dict[str, Any]:
    eq = row.get("evidence_quality") or row.get("evidence_quality_summary") or {}
    if not isinstance(eq, dict):
        eq = {}
    return {
        "raw_status": eq.get("raw_status"),
        "content_quality": eq.get("content_quality") or row.get("content_quality"),
        "documents_with_text": eq.get("documents_with_text"),
        "text_chars": eq.get("text_chars"),
    }


def deadline_authority(row: dict[str, Any]) -> dict[str, Any]:
    da = row.get("deadline_authority") if isinstance(row.get("deadline_authority"), dict) else {}
    conflicts = row.get("authority_conflicts") if isinstance(row.get("authority_conflicts"), dict) else {}
    dconf = conflicts.get("deadline") if isinstance(conflicts.get("deadline"), dict) else {}
    return {
        "status": row.get("deadline_authority_status") or da.get("status") or dconf.get("status"),
        "conflict": bool(da.get("conflict") or dconf.get("conflict")),
        "authoritative_submission_date": da.get("authoritative_submission_date") or dconf.get("authoritative_submission_date"),
    }


def candidate_payload(index_row: dict[str, Any], raw: dict[str, Any] | None, run_id: int | None, shard: int | None) -> dict[str, Any]:
    raw = raw or {}
    merged = dict(index_row)
    for field in (
        "title", "buyer", "portal", "notice_url", "deadline", "estimated_value", "currency",
        "content_quality", "gate_readiness", "evidence_gate_coverage", "spm_post_dce_score",
        "spm_fit_band", "spm_fit_reasons", "spm_friction_signals",
    ):
        if raw.get(field) not in (None, "", [], {}):
            merged[field] = raw.get(field)
    locator = index_row.get("artifact_locator") if isinstance(index_row.get("artifact_locator"), dict) else {}
    return {
        "candidate_id": cid(index_row),
        "title": merged.get("title"),
        "buyer": merged.get("buyer"),
        "portal": merged.get("portal"),
        "notice_url": merged.get("notice_url"),
        "deadline": merged.get("deadline"),
        "estimated_value": merged.get("estimated_value"),
        "currency": merged.get("currency"),
        "review_stage": "BUSINESS_GATES",
        "gate_readiness": bool(merged.get("gate_readiness")),
        "content_quality": merged.get("content_quality"),
        "evidence_gate_coverage": int(merged.get("evidence_gate_coverage") or 0),
        "spm_post_dce_score": int(merged.get("spm_post_dce_score") or 0),
        "spm_fit_band": merged.get("spm_fit_band"),
        "spm_fit_reasons": merged.get("spm_fit_reasons") or [],
        "spm_friction_signals": merged.get("spm_friction_signals") or [],
        "upstream_classification": raw.get("classification"),
        "deadline_authority": deadline_authority(raw) if raw else {
            "status": index_row.get("deadline_authority_status"),
            "conflict": False,
            "authoritative_submission_date": None,
        },
        "evidence_quality": raw_quality(raw) if raw else {},
        "gate_evidence": gate_evidence(raw) if raw else {},
        "raw_dce_row_found": bool(raw),
        "artifact_locator": {
            "dce_run_id": run_id or index_row.get("source_dce_run_id") or locator.get("dce_run_id"),
            "shard": shard if shard is not None else index_row.get("source_shard", locator.get("shard")),
            "candidate_id": cid(index_row),
            "release_tag": locator.get("release_tag") or (
                f"dce-harvest-{run_id or index_row.get('source_dce_run_id')}"
                if (run_id or index_row.get("source_dce_run_id")) else None
            ),
        },
        "finality": "NOT_A_VERDICT_ASSISTANT_MUST_ADJUDICATE",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="control/gpt_review_index.json")
    ap.add_argument("--release-root", required=True)
    ap.add_argument("--out-dir", default="control/gpt_gate_stress_batches")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()

    index = load(Path(args.index))
    source_items = [x for x in (index.get("items") or []) if isinstance(x, dict)]
    gates = [x for x in source_items if str(x.get("review_stage") or "").upper() == "BUSINESS_GATES" and bool(x.get("gate_readiness"))]

    targets: dict[str, dict[str, Any]] = {}
    duplicate_target_ids: list[str] = []
    for row in gates:
        k = key(cid(row))
        if not k:
            continue
        if k in targets:
            duplicate_target_ids.append(cid(row))
            continue
        targets[k] = row

    raw_best: dict[str, tuple[int, int, dict[str, Any]]] = {}
    shard_files = sorted(Path(args.release_root).rglob("fast-adjudication-shard-*.jsonl"))
    scanned_rows = 0
    for path in shard_files:
        run_id, shard = run_and_shard(path)
        for row in load_jsonl(path):
            scanned_rows += 1
            k = key(cid(row))
            if k not in targets:
                continue
            target_run = int(targets[k].get("source_dce_run_id") or 0)
            # Prefer the exact DCE generation recorded by the durable review index;
            # otherwise use the newest retrieved version as a transparent fallback.
            exact = int(bool(target_run and run_id == target_run))
            rank = (exact, int(run_id or 0), int(shard or 0))
            cur = raw_best.get(k)
            if cur is None or rank > (int(bool(target_run and cur[0] == target_run)), cur[0], cur[1]):
                raw_best[k] = (int(run_id or 0), int(shard or 0), row)

    payloads = []
    for k, idx_row in targets.items():
        found = raw_best.get(k)
        if found:
            run_id, shard, raw = found
            payloads.append(candidate_payload(idx_row, raw, run_id, shard))
        else:
            payloads.append(candidate_payload(idx_row, None, None, None))

    # Preserve the durable index ordering. It is a mechanical ordering only; the
    # assistant still adjudicates every emitted candidate.
    order = {key(cid(row)): i for i, row in enumerate(gates)}
    payloads.sort(key=lambda x: order.get(key(x.get("candidate_id")), 10**9))

    batch_size = max(1, min(20, int(args.batch_size)))
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for start in range(0, len(payloads), batch_size):
        chunk = payloads[start:start + batch_size]
        idx = start // batch_size
        name = f"batch-{idx:03d}.json"
        body = {
            "schema": "GPT_GATE_STRESS_BATCH_V1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batch_index": idx,
            "start_rank": start + 1,
            "end_rank": start + len(chunk),
            "count": len(chunk),
            "items": chunk,
            "instruction": "Exhaustive BUSINESS_GATES stress surface. Assistant must adjudicate every item; generator never emits GREEN/YELLOW/RED.",
        }
        (out_dir / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files.append({"file": name, "start_rank": start + 1, "end_rank": start + len(chunk), "count": len(chunk)})

    raw_missing = [x["candidate_id"] for x in payloads if not x.get("raw_dce_row_found")]
    bands = Counter(str(x.get("spm_fit_band") or "UNKNOWN") for x in payloads)
    runs = sorted({int(x.get("source_dce_run_id") or 0) for x in gates if int(x.get("source_dce_run_id") or 0)}, reverse=True)
    manifest = {
        "schema": "GPT_GATE_STRESS_MANIFEST_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_index_schema": index.get("schema"),
        "source_index_count": int(index.get("count") or len(source_items)),
        "business_gates_in_index": len(gates),
        "unique_business_gate_ids": len(targets),
        "duplicate_target_ids": duplicate_target_ids,
        "emitted_candidates": len(payloads),
        "raw_dce_rows_recovered": len(payloads) - len(raw_missing),
        "raw_dce_rows_missing": len(raw_missing),
        "missing_candidate_ids": raw_missing,
        "release_runs_required": runs,
        "shard_files_scanned": len(shard_files),
        "adjudication_rows_scanned": scanned_rows,
        "by_spm_fit_band": dict(bands),
        "batch_size": batch_size,
        "batch_count": len(files),
        "files": files,
        "conservation_pass": len(payloads) == len(targets) == len(gates) and not duplicate_target_ids and not raw_missing,
        "contract": "Mechanical exhaustive DCE evidence surface only. No automated verdict. Conservation must pass before assistant stress adjudication is trusted.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not manifest["conservation_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
