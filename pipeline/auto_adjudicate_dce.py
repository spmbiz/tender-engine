from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from authority_conflicts import process as reconcile_authority
from final_verdict_guard import REQUIRED_GATES


def load_jsonl(path: Path):
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj


def evidence_map(row: dict) -> dict:
    snippets = row.get("gate_snippets") or row.get("evidence_by_gate") or {}
    if not isinstance(snippets, dict):
        return {}
    for nested_key in ("categories", "gate_evidence", "evidence_by_gate"):
        nested = snippets.get(nested_key)
        if isinstance(nested, dict):
            return nested
    return snippets


def compact_review_evidence(row: dict, per_gate: int = 4, chars: int = 1800) -> dict:
    snippets = evidence_map(row)
    packed = {}
    for gate in REQUIRED_GATES:
        out = []
        for item in list(snippets.get(gate) or [])[:per_gate]:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("snippet") or item.get("evidence") or "")
                source = (
                    item.get("source")
                    or item.get("file")
                    or item.get("path")
                    or item.get("document")
                    or item.get("document_path")
                )
                match = item.get("match")
                provenance = {
                    "source_url": item.get("source_url"),
                    "source_sha256": item.get("source_sha256"),
                    "source_kind": item.get("source_kind"),
                    "source_provenance_match": item.get("source_provenance_match"),
                    "provenance_strength": item.get("provenance_strength"),
                    "raw_machine_format": bool(item.get("raw_machine_format")),
                    "corpus_start": item.get("start"),
                    "corpus_end": item.get("end"),
                }
            else:
                text = str(item or "")
                source = None
                match = None
                provenance = {
                    "source_url": None,
                    "source_sha256": None,
                    "source_kind": None,
                    "source_provenance_match": None,
                    "provenance_strength": "UNATTRIBUTED_LEGACY_SNIPPET",
                    "raw_machine_format": False,
                    "corpus_start": None,
                    "corpus_end": None,
                }
            text = " ".join(text.split())[:chars]
            if text:
                record = {"text": text, "source": source, **provenance}
                if match not in (None, ""):
                    record["match"] = match
                out.append(record)
        packed[gate] = out
    return packed


def refresh_authority(row: dict) -> dict:
    if not row.get("gate_readiness"):
        return row
    rel = str(row.get("artifact_relative_root") or "").strip()
    if not rel:
        return row
    base = Path(os.getenv("DCE_FAST_ROOT", "out")) / rel
    if not (base / "manifest.json").exists():
        return row
    try:
        authority = reconcile_authority(base)
    except Exception as exc:
        row["authority_refresh_error"] = str(exc)[:500]
        return row
    row["authority_conflicts"] = authority
    deadline = authority.get("deadline") if isinstance(authority, dict) else None
    if isinstance(deadline, dict):
        row["deadline_authority_status"] = deadline.get("status")
        row["deadline_conflict"] = bool(deadline.get("conflict"))
    return row


def fallback_record(row: dict, reason: str, classification: str = "MODEL_REVIEW_REQUIRED") -> dict:
    try:
        prelim = min(89, int(float(row.get("preliminary_score") or 0)))
    except Exception:
        prelim = 0
    evidence = compact_review_evidence(row)
    attributed = sum(
        1 for vals in evidence.values() for item in vals
        if isinstance(item, dict) and item.get("source") and item.get("source_sha256")
    )
    unattributed = sum(
        1 for vals in evidence.values() for item in vals
        if isinstance(item, dict) and not item.get("source")
    )
    return {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title"),
        "buyer": row.get("buyer"),
        "portal": row.get("portal"),
        "notice_url": row.get("notice_url"),
        "deadline": row.get("deadline"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "preliminary_score": row.get("preliminary_score"),
        "classification": classification,
        "final_score": prelim,
        "summary": reason,
        "model": None,
        "model_review_completed": False,
        "review_provider": "GPT_WEB_HANDOFF",
        "content_quality": row.get("content_quality"),
        "gate_readiness": bool(row.get("gate_readiness")),
        "evidence_quality": row.get("evidence_quality") or {},
        "evidence_provenance_summary": {
            "attributed_snippets": attributed,
            "unattributed_snippets": unattributed,
            "all_review_snippets_attributed": bool(attributed and not unattributed),
        },
        "authority_conflicts": row.get("authority_conflicts") or {},
        "gate_evidence_candidates": evidence,
        "gates": {
            gate: {
                "status": "UNKNOWN",
                "evidence": [],
                "notes": "Awaiting GPT Web adjudication; absence of bidder evidence is never a PASS.",
            }
            for gate in REQUIRED_GATES
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-model-reviews", type=int, default=0)
    ap.add_argument("--model-concurrency", type=int, default=0)
    ap.add_argument("--model-retries", type=int, default=0)
    args = ap.parse_args()

    rows = [refresh_authority(r) for r in load_jsonl(Path(args.queue))]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    gate_ready_rows = []

    for row in rows:
        if not row.get("gate_readiness"):
            records.append(
                fallback_record(
                    row,
                    "Not gate-ready: authoritative DCE evidence is incomplete or unverified.",
                    classification="YELLOW",
                )
            )
            continue
        gate_ready_rows.append(row)
        records.append(
            fallback_record(
                row,
                "Authoritative DCE is gate-ready. Final business adjudication is intentionally delegated to the persistent GPT Web review bank; GitHub Actions performs no remote LLM/API adjudication.",
            )
        )

    with (out / "adjudication.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    counts = Counter(str(r.get("classification") or "UNKNOWN") for r in records)
    review_required = [r for r in records if r.get("classification") == "MODEL_REVIEW_REQUIRED"]
    review_required.sort(key=lambda r: int(r.get("final_score") or 0), reverse=True)

    (out / "supergreen_shortlist.json").write_text(
        json.dumps(
            {
                "dce_candidates": len(rows),
                "gate_ready": len(gate_ready_rows),
                "final_supergreen": 0,
                "green_or_partnerable": 0,
                "items": [],
                "note": "GitHub Actions is intentionally API-free. Final verdicts are produced by GPT Web from the persistent DCE review bank.",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (out / "review_required.json").write_text(
        json.dumps(review_required[:120], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = {
        "candidates": len(rows),
        "gate_ready": len(gate_ready_rows),
        "model_available": False,
        "model": None,
        "remote_model_calls_enabled": False,
        "review_provider": "GPT_WEB_HANDOFF",
        "classification_counts": dict(counts),
        "final_supergreen": 0,
        "green_or_partnerable": 0,
        "review_required": len(review_required),
        "chatgpt_hot_review_ready": sum(
            1
            for r in review_required
            if r.get("gate_readiness") and any(r.get("gate_evidence_candidates", {}).values())
        ),
        "review_snippet_provenance": {
            "attributed": sum(int((r.get("evidence_provenance_summary") or {}).get("attributed_snippets") or 0) for r in records),
            "unattributed": sum(int((r.get("evidence_provenance_summary") or {}).get("unattributed_snippets") or 0) for r in records),
        },
        "guard_contract": "GitHub never promotes FINAL_SUPER_GREEN. GPT Web must adjudicate authoritative gates; missing evidence remains UNKNOWN. Every new gate snippet carries extracted-document provenance where the DCE corpus index can attribute it.",
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
