from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from authority_conflicts import process as process_authority_conflicts
from build_gpt_dce_read_layer import build_candidate_layer

KEEP_FILES = {
    "candidate.json",
    "manifest.json",
    "ted_resolution.json",
    "document_index.json",
    "corpus.txt",
    "evidence_quality.json",
    "gate_snippets.json",
    "authority_conflicts.json",
}
ROOT_KEEP = {"batch_results.json", "batch_summary.json"}


def tree_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    ap.add_argument("--out", default="slim")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    raw_bytes = tree_bytes(root)
    statuses = Counter()
    evidence_qualities = Counter()
    authority_statuses = Counter()
    gate_ready = 0
    deadline_conflicts = 0
    candidates = 0
    copied_files = 0
    gpt_read_candidates = 0
    gpt_read_files = 0
    gpt_read_errors = 0

    for manifest_path in sorted(root.rglob("manifest.json")):
        candidate_root = manifest_path.parent
        try:
            rel_root = candidate_root.relative_to(root)
        except ValueError:
            continue
        target_root = out / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        manifest = load_json(manifest_path) or {}
        statuses[str(manifest.get("status") or "UNKNOWN")] += 1
        evidence = load_json(candidate_root / "evidence_quality.json") or {}
        if evidence:
            evidence_qualities[str(evidence.get("content_quality") or "UNKNOWN")] += 1
            gate_ready += int(bool(evidence.get("gate_readiness")))
        try:
            authority = process_authority_conflicts(candidate_root)
        except Exception:
            authority = load_json(candidate_root / "authority_conflicts.json") or {}
        deadline = authority.get("deadline") if isinstance(authority, dict) else {}
        if isinstance(deadline, dict):
            authority_statuses[str(deadline.get("status") or "UNKNOWN")] += 1
            deadline_conflicts += int(bool(deadline.get("conflict")))
        candidates += 1

        # Build the GPT-native Markdown navigation layer only after corpus, evidence
        # quality and gate snippets exist. Failure here must never destroy the
        # canonical machine-readable handoff.
        try:
            build_candidate_layer(candidate_root)
            gpt_read_candidates += 1
        except Exception:
            gpt_read_errors += 1

        for name in KEEP_FILES:
            src = candidate_root / name
            if src.is_file():
                shutil.copy2(src, target_root / name)
                copied_files += 1

        gpt_read = candidate_root / "gpt_read"
        if gpt_read.is_dir():
            target_gpt = target_root / "gpt_read"
            shutil.copytree(gpt_read, target_gpt, dirs_exist_ok=True)
            count = sum(1 for p in target_gpt.rglob("*") if p.is_file())
            copied_files += count
            gpt_read_files += count

        corpus = candidate_root / "corpus.txt"
        portal_page = candidate_root / "portal_page.txt"
        if (not corpus.exists() or corpus.stat().st_size == 0) and portal_page.is_file():
            text = portal_page.read_text(encoding="utf-8", errors="replace")[:250_000]
            (target_root / "portal_page.txt").write_text(text, encoding="utf-8")
            copied_files += 1

    for name in ROOT_KEEP:
        src = root / name
        if src.is_file():
            shutil.copy2(src, out / name)
            copied_files += 1

    slim_bytes_before_metrics = tree_bytes(out)
    metrics = {
        "candidates": candidates,
        "status_counts": dict(statuses),
        "evidence_quality_counts": dict(evidence_qualities),
        "authority_deadline_status_counts": dict(authority_statuses),
        "deadline_conflicts": deadline_conflicts,
        "gate_ready": gate_ready,
        "gate_blocked": max(0, candidates - gate_ready),
        "gpt_read_candidates": gpt_read_candidates,
        "gpt_read_files": gpt_read_files,
        "gpt_read_errors": gpt_read_errors,
        "raw_worker_tree_bytes": raw_bytes,
        "slim_handoff_bytes_before_metrics": slim_bytes_before_metrics,
        "bytes_removed": max(0, raw_bytes - slim_bytes_before_metrics),
        "reduction_ratio": round((1 - slim_bytes_before_metrics / raw_bytes) if raw_bytes else 0, 6),
        "copied_files": copied_files,
        "raw_archives_retained_in_artifact": False,
        "contract": "handoff keeps manifests, evidence quality, authority conflicts, extracted corpus, document index, gate snippets, GPT-readable Markdown navigation and batch metrics; raw DCE files stay runner-local",
    }
    (out / "_shard_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    metrics["slim_handoff_bytes"] = tree_bytes(out)
    (out / "_shard_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
