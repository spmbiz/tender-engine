from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

JSON_FILES = (
    "candidate.json",
    "manifest.json",
    "document_index.json",
    "evidence_quality.json",
    "gate_snippets.json",
    "authority_conflicts.json",
    "_canonical_pack_manifest.json",
    "ted_resolution.json",
)


def load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Extracted canonical candidate pack")
    ap.add_argument("--candidate-id", required=True)
    ap.add_argument("--source-run", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Missing focus root: {root}")

    payload: dict[str, Any] = {
        "schema": "FOCUS_DCE_REVIEW_V1",
        "candidate_id": args.candidate_id,
        "source_dce_run_id": int(args.source_run) if str(args.source_run).isdigit() else args.source_run,
        "review_contract": (
            "Full candidate-specific canonical DCE pack for focused ChatGPT adjudication. "
            "This artifact is evidence, not a verdict. Unknown is never PASS and FINAL_SUPER_GREEN "
            "requires every mandatory gate plus authoritative deadline reconciliation."
        ),
    }
    for name in JSON_FILES:
        obj = load_json(root / name)
        if obj is not None:
            payload[name.removesuffix(".json")] = obj

    corpus_path = root / "corpus.txt"
    corpus = corpus_path.read_text(encoding="utf-8", errors="replace") if corpus_path.is_file() else ""
    payload["corpus_char_count"] = len(corpus)
    payload["corpus_text"] = corpus

    portal_page = root / "portal_page.txt"
    if portal_page.is_file():
        payload["portal_page_text"] = portal_page.read_text(encoding="utf-8", errors="replace")

    originals = []
    original_root = root / "originals"
    if original_root.is_dir():
        for p in sorted(original_root.iterdir()):
            if p.is_file():
                originals.append({"name": p.name, "bytes": p.stat().st_size})
    payload["original_files"] = originals

    manifest = payload.get("manifest") or {}
    manifest_cid = str(manifest.get("candidate_id") or "") if isinstance(manifest, dict) else ""
    payload["candidate_id_match"] = not manifest_cid or manifest_cid == args.candidate_id
    if not payload["candidate_id_match"]:
        raise SystemExit(f"Candidate mismatch: requested={args.candidate_id!r} manifest={manifest_cid!r}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": payload["schema"],
        "candidate_id": args.candidate_id,
        "source_dce_run_id": payload["source_dce_run_id"],
        "corpus_char_count": len(corpus),
        "original_files": len(originals),
        "gate_readiness": ((payload.get("evidence_quality") or {}).get("gate_readiness") if isinstance(payload.get("evidence_quality"), dict) else None),
        "out": str(out),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
