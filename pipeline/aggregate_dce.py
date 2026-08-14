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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="dce-artifacts")
    ap.add_argument("--out", default="dce-aggregate")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    counts = Counter()

    for manifest_path in sorted(root.rglob("manifest.json")):
        manifest = load(manifest_path)
        if not isinstance(manifest, dict) or "candidate_id" not in manifest:
            continue
        candidate_root = manifest_path.parent
        candidate = manifest.get("candidate") or load(candidate_root / "candidate.json") or {}
        gates = load(candidate_root / "gate_snippets.json") or {}
        doc_index = load(candidate_root / "document_index.json") or []
        corpus_path = candidate_root / "corpus.txt"
        status = manifest.get("status") or "UNKNOWN"
        counts[status] += 1
        row = {
            "candidate_id": manifest.get("candidate_id"),
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
        rows.append(row)

    with (out / "deep_review_queue.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "candidates": len(rows),
        "status_counts": dict(counts),
        "downloaded_public": counts.get("DOWNLOADED_PUBLIC", 0),
        "fully_extracted": sum(1 for r in rows if r.get("corpus_chars", 0) > 0),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
