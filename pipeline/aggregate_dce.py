from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


PORTAL_GENERIC_FILE_PATTERNS = [
    re.compile(r"^depot[-_ ]?pli\.pdf$", re.I),
    re.compile(r"^CGU.*marches.*\.pdf$", re.I),
    re.compile(r"^rib-tender-nutzungsbedingungen.*\.pdf$", re.I),
    re.compile(r"^agb\.pdf$", re.I),
    re.compile(r"^Datenschutzbestimmungen_Vergabe-Abteilung\.pdf$", re.I),
    re.compile(r"^BOE-A-2017-12902-E\.pdf$", re.I),
]


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def is_portal_generic_file(file_rec: dict) -> bool:
    name = str((file_rec or {}).get("name") or "").strip()
    return bool(name) and any(rx.search(name) for rx in PORTAL_GENERIC_FILE_PATTERNS)


def legacy_content_quality(raw_status: str, files: list[dict]) -> tuple[str, str, bool]:
    if raw_status != "DOWNLOADED_PUBLIC":
        return raw_status, "NOT_APPLICABLE", False
    if not files:
        return "DOWNLOADED_PUBLIC_EMPTY", "EXTRACTION_EMPTY", False
    substantive = [f for f in files if not is_portal_generic_file(f)]
    if not substantive:
        return "PORTAL_GENERIC_ONLY", "PORTAL_GENERIC_ONLY", False
    return "DCE_CONTENT_UNVERIFIED", "UNKNOWN_RETRIEVED_DOCUMENT", False


def resolve_evidence(raw_status: str, files: list[dict], evidence: dict) -> tuple[str, str, bool]:
    if isinstance(evidence, dict) and evidence.get("contract") == "DCE_EVIDENCE_QUALITY_V1":
        return (
            str(evidence.get("derived_status") or raw_status),
            str(evidence.get("content_quality") or "UNKNOWN"),
            bool(evidence.get("gate_readiness")),
        )
    return legacy_content_quality(raw_status, files)


def quality_key(row: dict) -> tuple:
    return (
        bool(row.get("gate_readiness")),
        row.get("status") == "DOWNLOADED_PUBLIC",
        int(row.get("corpus_chars") or 0),
        int(row.get("documents_extracted") or 0),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="dce-artifacts")
    ap.add_argument("--out", default="dce-aggregate")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    by_candidate: dict[str, dict] = {}
    raw_manifest_rows = 0

    for manifest_path in sorted(root.rglob("manifest.json")):
        manifest = load(manifest_path)
        if not isinstance(manifest, dict) or "candidate_id" not in manifest:
            continue
        raw_manifest_rows += 1
        candidate_root = manifest_path.parent
        candidate = manifest.get("candidate") or load(candidate_root / "candidate.json") or {}
        gates = load(candidate_root / "gate_snippets.json") or {}
        evidence = load(candidate_root / "evidence_quality.json") or {}
        doc_index = load(candidate_root / "document_index.json") or []
        corpus_path = candidate_root / "corpus.txt"
        raw_status = str(manifest.get("status") or "UNKNOWN")
        files = manifest.get("files") or []
        status, content_quality, gate_readiness = resolve_evidence(raw_status, files, evidence)
        cid = str(manifest.get("candidate_id"))
        row = {
            "candidate_id": cid,
            "title": candidate.get("title"),
            "buyer": candidate.get("buyer"),
            "portal": manifest.get("portal"),
            "raw_status": raw_status,
            "status": status,
            "content_quality": content_quality,
            "gate_readiness": gate_readiness,
            "evidence_quality": evidence,
            "deadline": candidate.get("deadline"),
            "estimated_value": candidate.get("estimated_value"),
            "currency": candidate.get("currency"),
            "notice_url": candidate.get("notice_url"),
            "preliminary_score": candidate.get("preliminary_score") or candidate.get("pre_score"),
            "files": files,
            "documents_extracted": len(doc_index) if isinstance(doc_index, list) else 0,
            "corpus_chars": corpus_path.stat().st_size if corpus_path.exists() else 0,
            "gate_evidence_counts": gates.get("evidence_counts") or {},
            "gate_snippets": gates.get("categories") or {},
            "artifact_relative_root": str(candidate_root.relative_to(root)),
            "gpt_instruction": (
                "DOWNLOADED_PUBLIC is transport success, not proof of DCE. Only review mandatory gates when gate_readiness=true. "
                "ACCESS_GUIDE_ONLY / PORTAL_GENERIC_ONLY / DCE_CONTENT_UNVERIFIED are not authoritative DCE evidence. "
                "Resolve every mandatory gate as PASS/PASS_CONDITIONAL/FAIL_HARD/UNKNOWN/NOT_APPLICABLE with source evidence. "
                "FINAL_SUPER_GREEN or score >=90 is forbidden while any potentially disqualifying gate is UNKNOWN/FAIL or lacks evidence."
            ),
        }
        current = by_candidate.get(cid.casefold())
        if current is None or quality_key(row) > quality_key(current):
            by_candidate[cid.casefold()] = row

    rows = sorted(by_candidate.values(), key=lambda r: str(r.get("candidate_id") or ""))
    counts = Counter(str(r.get("status") or "UNKNOWN") for r in rows)
    raw_counts = Counter(str(r.get("raw_status") or "UNKNOWN") for r in rows)
    quality_counts = Counter(str(r.get("content_quality") or "UNKNOWN") for r in rows)

    with (out / "deep_review_queue.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    batch_results = []
    for path in sorted(root.rglob("batch_results.json")):
        obj = load(path)
        if isinstance(obj, list):
            batch_results.extend(x for x in obj if isinstance(x, dict))

    shard_metrics = []
    for path in sorted(root.rglob("_shard_metrics.json")):
        obj = load(path)
        if isinstance(obj, dict):
            shard_metrics.append(obj)

    raw_bytes = sum(int(x.get("raw_worker_tree_bytes") or 0) for x in shard_metrics)
    slim_bytes = sum(int(x.get("slim_handoff_bytes") or x.get("slim_handoff_bytes_before_metrics") or 0) for x in shard_metrics)
    retries = sum(int(x.get("retries") or 0) for x in batch_results)
    rate_limited = sum(1 for x in batch_results if x.get("rate_limited"))
    worker_failures = sum(1 for x in batch_results if int(x.get("returncode") or 0) != 0)
    gate_ready_count = sum(1 for r in rows if r.get("gate_readiness"))

    summary = {
        "candidates": len(rows),
        "raw_manifest_rows": raw_manifest_rows,
        "duplicate_manifest_rows_removed": max(0, raw_manifest_rows - len(rows)),
        "raw_status_counts": dict(raw_counts),
        "derived_status_counts": dict(counts),
        "content_quality_counts": dict(quality_counts),
        "raw_downloaded_public": raw_counts.get("DOWNLOADED_PUBLIC", 0),
        "gate_ready_substantive_dce": gate_ready_count,
        "gate_blocked_or_unverified": max(0, len(rows) - gate_ready_count),
        "access_guide_only": quality_counts.get("ACCESS_GUIDE_ONLY", 0),
        "portal_generic_only": quality_counts.get("PORTAL_GENERIC_ONLY", 0),
        "content_unverified": quality_counts.get("UNKNOWN_RETRIEVED_DOCUMENT", 0),
        "fully_extracted_gate_ready": sum(1 for r in rows if r.get("gate_readiness") and r.get("corpus_chars", 0) > 0),
        "worker_retries": retries,
        "worker_failures": worker_failures,
        "rate_limit_signals": rate_limited,
        "shard_metric_count": len(shard_metrics),
        "raw_worker_tree_bytes": raw_bytes,
        "slim_handoff_bytes": slim_bytes,
        "handoff_storage_reduction_ratio": round((1 - slim_bytes / raw_bytes) if raw_bytes else 0, 6),
        "raw_archives_in_final_artifact": False,
        "contract": "Only gate_ready_substantive_dce rows may advance to mandatory-gate adjudication; final 90+/FINAL_SUPER_GREEN still requires complete evidenced gate resolution.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
