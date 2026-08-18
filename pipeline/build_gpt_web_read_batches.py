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
        # Display-only cleanup. The artifact remains authoritative and addressable
        # by source/hash; stripping markup here prevents raw Word/XML tags from
        # crowding the small GPT read surface.
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
        "evidence_instruction": "A compact snippet without document path+SHA is navigation evidence only. Follow artifact_locator before resolving a mandatory gate from legacy/unattributed material. Raw machine-format text is display-cleaned but must still be checked against its source artifact.",
        "finality": "NOT_A_VERDICT_ASSISTANT_MUST_ADJUDICATE",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default="control/gpt_supergreen_inbox.json")
    ap.add_argument("--out-dir", default="control/gpt_web_read_batches")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()

    inbox = load(Path(args.inbox))
    rows = inbox.get("review_queue") or inbox.get("pending_final_review") or []
    rows = [compact(x) for x in rows if isinstance(x, dict) and x.get("candidate_id")]
    batch_size = max(1, min(25, int(args.batch_size)))
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        idx = start // batch_size
        name = f"batch-{idx:03d}.json"
        payload = {
            "schema": "GPT_WEB_READ_BATCH_V2_PROVENANCE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_inbox_updated_at": inbox.get("updated_at"),
            "latest_source_dce_run_id": inbox.get("latest_source_dce_run_id"),
            "batch_index": idx,
            "start_rank": start + 1,
            "end_rank": start + len(chunk),
            "count": len(chunk),
            "items": chunk,
            "instruction": "Assistant adjudicates these DCE-backed candidates. Compact snippets with provenance_strength LEGACY_UNATTRIBUTED/LEGACY_PATH_ONLY are not sufficient to resolve a mandatory gate; follow artifact_locator. Unknown is never PASS and this file never emits a final verdict automatically.",
        }
        (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files.append({"file": name, "start_rank": start + 1, "end_rank": start + len(chunk), "count": len(chunk)})

    manifest = {
        "schema": "GPT_WEB_READ_BATCH_MANIFEST_V2_PROVENANCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_inbox_updated_at": inbox.get("updated_at"),
        "latest_source_dce_run_id": inbox.get("latest_source_dce_run_id"),
        "rich_window_count": len(rows),
        "batch_size": batch_size,
        "batch_count": len(files),
        "files": files,
        "contract": "Mechanical split/compaction only. New DCE snippets retain exact document provenance. Legacy unattributed snippets force artifact lookup before gate resolution. GPT Web adjudicator is the assistant, not a repository worker.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
