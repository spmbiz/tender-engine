from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GATES = (
    "entity_geography", "turnover_financial", "references_experience",
    "certifications_partner", "staffing_team", "insurance_bonds",
    "subcontracting_consortium", "deliverables_scope", "sla_onsite",
    "term_value", "award_criteria", "forms_signatures", "submission",
    "ip_data_security", "payment_tax",
)


def clip(value: Any, chars: int = 520) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= chars else text[: chars - 1] + "…"


def display_text(item: dict[str, Any]) -> str:
    raw = str(item.get("text") or item.get("snippet") or item.get("context") or "")
    if item.get("raw_machine_format"):
        raw = html.unescape(re.sub(r"<[^>]{1,240}>", " ", raw))
    return clip(raw)


def load(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def evidence(row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw = row.get("evidence_by_gate") or row.get("gate_evidence_candidates") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for gate in GATES:
        vals = raw.get(gate)
        if not isinstance(vals, list):
            continue
        kept = []
        for item in vals[:2]:
            if isinstance(item, dict):
                text = display_text(item)
                if text:
                    source = item.get("source") or item.get("file") or item.get("path")
                    kept.append({
                        "text": text,
                        "source": source,
                        "source_url": item.get("source_url"),
                        "source_sha256": item.get("source_sha256"),
                        "source_kind": item.get("source_kind"),
                        "provenance_strength": item.get("provenance_strength") or ("LEGACY_UNATTRIBUTED" if not source else "LEGACY_PATH_ONLY"),
                        "raw_machine_format": bool(item.get("raw_machine_format")),
                        "artifact_lookup_required": not bool(source and item.get("source_sha256")),
                    })
            elif str(item or "").strip():
                kept.append({
                    "text": clip(item),
                    "source": None,
                    "source_url": None,
                    "source_sha256": None,
                    "source_kind": None,
                    "provenance_strength": "LEGACY_UNATTRIBUTED",
                    "raw_machine_format": False,
                    "artifact_lookup_required": True,
                })
        if kept:
            out[gate] = kept
    return out


def source_run(row: dict[str, Any]) -> int | None:
    for value in (
        row.get("source_dce_run_id"),
        (row.get("artifact_locator") or {}).get("dce_run_id") if isinstance(row.get("artifact_locator"), dict) else None,
        (row.get("evidence_locator") or {}).get("dce_run_id") if isinstance(row.get("evidence_locator"), dict) else None,
    ):
        if str(value or "").isdigit():
            return int(value)
    return None


def apply_provenance_override(row: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    candidate = str(row.get("candidate_id") or "").strip()
    override = overrides.get(candidate)
    if not isinstance(override, dict):
        return row
    current_run = source_run(row)
    override_run = override.get("source_dce_run_id")
    if current_run is None or not str(override_run or "").isdigit() or current_run != int(override_run):
        return row
    refreshed = dict(row)
    if isinstance(override.get("evidence_by_gate"), dict):
        refreshed["evidence_by_gate"] = override["evidence_by_gate"]
        refreshed["gate_evidence_candidates"] = override["evidence_by_gate"]
        refreshed["evidence_gate_coverage"] = sum(1 for vals in override["evidence_by_gate"].values() if isinstance(vals, list) and vals)
    if isinstance(override.get("evidence_quality_summary"), dict):
        refreshed["evidence_quality_summary"] = override["evidence_quality_summary"]
    if isinstance(override.get("evidence_provenance_summary"), dict):
        refreshed["evidence_provenance_summary"] = override["evidence_provenance_summary"]
    refreshed["provenance_override"] = {
        "applied": True,
        "refreshed_at": override.get("refreshed_at"),
        "source_dce_run_id": int(override_run),
        "release_tag": override.get("release_tag"),
        "archive_name": override.get("archive_name"),
        "bundle_asset": override.get("bundle_asset"),
        "policy": "Evidence provenance/presentation refresh only; ranking and procurement verdict are unchanged.",
    }
    return refreshed


def compact(row: dict[str, Any]) -> dict[str, Any]:
    da = row.get("deadline_authority") if isinstance(row.get("deadline_authority"), dict) else {}
    eq = row.get("evidence_quality_summary") if isinstance(row.get("evidence_quality_summary"), dict) else {}
    locator = row.get("artifact_locator") if isinstance(row.get("artifact_locator"), dict) else {}
    ev = evidence(row)
    snippets = [item for vals in ev.values() for item in vals if isinstance(item, dict)]
    attributed = sum(1 for item in snippets if item.get("source") and item.get("source_sha256"))
    legacy_unattributed = sum(1 for item in snippets if item.get("artifact_lookup_required"))
    return {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title"),
        "buyer": row.get("buyer"),
        "portal": row.get("portal"),
        "notice_url": row.get("notice_url"),
        "deadline": row.get("deadline"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "review_stage": row.get("review_stage"),
        "gate_readiness": bool(row.get("gate_readiness")),
        "content_quality": row.get("content_quality"),
        "evidence_gate_coverage": row.get("evidence_gate_coverage"),
        "spm_post_dce_score": row.get("spm_post_dce_score"),
        "spm_fit_band": row.get("spm_fit_band"),
        "spm_fit_reasons": row.get("spm_fit_reasons") or [],
        "spm_friction_signals": row.get("spm_friction_signals") or [],
        "deadline_authority_status": row.get("deadline_authority_status"),
        "deadline_conflict": bool(da.get("conflict")),
        "authoritative_submission_date": da.get("authoritative_submission_date"),
        "source_dce_run_id": row.get("source_dce_run_id"),
        "source_shard": row.get("source_shard"),
        "review_key": row.get("review_key"),
        "artifact_locator": {
            "dce_run_id": locator.get("dce_run_id") or row.get("source_dce_run_id"),
            "shard": locator.get("shard") if locator.get("shard") is not None else row.get("source_shard"),
            "candidate_id": row.get("candidate_id"),
            "release_tag": locator.get("release_tag") or (f"dce-harvest-{row.get('source_dce_run_id')}" if row.get("source_dce_run_id") else None),
        },
        "evidence_quality": {
            "raw_status": eq.get("raw_status"),
            "documents_with_text": eq.get("documents_with_text"),
            "text_chars": eq.get("text_chars"),
            "attributed_compact_snippets": attributed,
            "artifact_lookup_required_snippets": legacy_unattributed,
            "all_compact_snippets_document_attributed": bool(snippets and attributed == len(snippets)),
        },
        "evidence": ev,
        "provenance_override": row.get("provenance_override"),
        "evidence_instruction": "A compact snippet without document path+SHA is navigation evidence only. Follow artifact_locator before resolving a mandatory gate from legacy/unattributed material. Raw machine-format text is display-cleaned but must still be checked against its source artifact.",
        "finality": "NOT_A_VERDICT_ASSISTANT_MUST_ADJUDICATE",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default="control/gpt_supergreen_inbox.json")
    ap.add_argument("--provenance-overrides", default="control/gpt_provenance_overrides.json")
    ap.add_argument("--out-dir", default="control/gpt_web_read_batches")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()

    inbox = load(Path(args.inbox))
    override_doc = load(Path(args.provenance_overrides))
    overrides = override_doc.get("overrides") if isinstance(override_doc.get("overrides"), dict) else {}
    raw_rows = inbox.get("review_queue") or inbox.get("pending_final_review") or []
    rows = [
        compact(apply_provenance_override(x, overrides))
        for x in raw_rows
        if isinstance(x, dict) and x.get("candidate_id")
    ]
    batch_size = max(1, min(25, int(args.batch_size)))
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    applied = sum(1 for row in rows if isinstance(row.get("provenance_override"), dict) and row["provenance_override"].get("applied"))
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        idx = start // batch_size
        name = f"batch-{idx:03d}.json"
        payload = {
            "schema": "GPT_WEB_READ_BATCH_V3_PROVENANCE_REFRESH",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_inbox_updated_at": inbox.get("updated_at"),
            "latest_source_dce_run_id": inbox.get("latest_source_dce_run_id"),
            "batch_index": idx,
            "start_rank": start + 1,
            "end_rank": start + len(chunk),
            "count": len(chunk),
            "items": chunk,
            "instruction": "Assistant adjudicates these DCE-backed candidates. Exact candidate/run provenance overrides may enrich legacy DCE from immutable canonical packs without changing ranking. Compact snippets still lacking path+SHA are navigation evidence only; follow artifact_locator. Unknown is never PASS.",
        }
        (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files.append({"file": name, "start_rank": start + 1, "end_rank": start + len(chunk), "count": len(chunk)})

    manifest = {
        "schema": "GPT_WEB_READ_BATCH_MANIFEST_V3_PROVENANCE_REFRESH",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_inbox_updated_at": inbox.get("updated_at"),
        "latest_source_dce_run_id": inbox.get("latest_source_dce_run_id"),
        "rich_window_count": len(rows),
        "provenance_override_count_available": len(overrides),
        "provenance_overrides_applied_in_window": applied,
        "batch_size": batch_size,
        "batch_count": len(files),
        "files": files,
        "contract": "Mechanical split/compaction only. New DCE snippets retain exact document provenance; exact candidate+source-run historical overrides may restore provenance from immutable canonical DCE packs. Neither mechanism changes ranking, eligibility or final verdict.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
