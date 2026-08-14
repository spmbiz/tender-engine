from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def quality_key(row: dict) -> tuple:
    return (
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
        doc_index = load(candidate_root / "document_index.json") or []
        corpus_path = candidate_root / "corpus.txt"
        status = manifest.get("status") or "UNKNOWN"
        cid = str(manifest.get("candidate_id"))
        row = {
            "candidate_id": cid,
            "title": candidate.get("title"),
            "buyer": candidate.get("buyer"),
            "portal": manifest.get("portal"),
            "status": status,
            "deadline": candidate.get("deadline"),
            "estimated_value": candidate.get("estimated_value"),
            "currency": candidate.get("currency"),
            "notice_url": candidate.get("notice_url"),
            "preliminary_score": candidate.get("preliminary_score") or candidate.get("pre_score"),
            "files": manifest.get("files") or [],
            "documents_extracted": len(doc_index) if isinstance(doc_index, list) else 0,
            "corpus_chars": corpus_path.stat().st_size if corpus_path.exists() else 0,
            "gate_evidence_counts": gates.get("evidence_counts") or {},
            "gate_snippets": gates.get("categories") or {},
            "artifact_relative_root": str(candidate_root.relative_to(root)),
            "gpt_instruction": (
                "Read the full corpus for this candidate when status is DOWNLOADED_PUBLIC. "
                "Resolve mandatory gates as PASS/PASS_CONDITIONAL/FAIL_HARD/UNKNOWN/NOT_APPLICABLE. "
                "No >=90 score without authoritative DCE evidence."
            ),
        }
        current = by_candidate.get(cid.casefold())
        if current is None or quality_key(row) > quality_key(current):
            by_candidate[cid.casefold()] = row

    rows = sorted(by_candidate.values(), key=lambda r: (str(r.get("candidate_id") or "")))
    counts = Counter(str(r.get("status") or "UNKNOWN") for r in rows)

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

    summary = {
        "candidates": len(rows),
        "raw_manifest_rows": raw_manifest_rows,
        "duplicate_manifest_rows_removed": max(0, raw_manifest_rows - len(rows)),
        "status_counts": dict(counts),
        "downloaded_public": counts.get("DOWNLOADED_PUBLIC", 0),
        "fully_extracted": sum(1 for r in rows if r.get("corpus_chars", 0) > 0),
        "worker_retries": retries,
        "worker_failures": worker_failures,
        "rate_limit_signals": rate_limited,
        "shard_metric_count": len(shard_metrics),
        "raw_worker_tree_bytes": raw_bytes,
        "slim_handoff_bytes": slim_bytes,
        "handoff_storage_reduction_ratio": round((1 - slim_bytes / raw_bytes) if raw_bytes else 0, 6),
        "raw_archives_in_final_artifact": False,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
