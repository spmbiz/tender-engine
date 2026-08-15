#!/usr/bin/env python3
"""Bundle immutable per-candidate DCE archives into a few bounded Release assets.

Workers emit immutable candidate-*.tar.gz files via temporary Actions artifacts.
The aggregate job is the only durable Release writer. This script groups those
already-compressed candidate packs into uncompressed TAR bundles so GitHub
Release persistence requires only a handful of API uploads instead of hundreds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Directory containing candidate-*.tar.gz packs")
    ap.add_argument("--out", required=True, help="Output directory for bounded release bundles")
    ap.add_argument("--max-bytes", type=int, default=1_200_000_000)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(root.rglob("candidate-*.tar.gz"))
    if not files:
        raise SystemExit("No candidate-*.tar.gz packs found")

    bundles: list[dict] = []
    current: list[Path] = []
    current_bytes = 0

    def flush() -> None:
        nonlocal current, current_bytes
        if not current:
            return
        idx = len(bundles)
        bundle = out / f"dce-canonical-packs-part-{idx:03d}.tar"
        with tarfile.open(bundle, "w") as tf:
            for p in current:
                tf.add(p, arcname=p.name, recursive=False)
        bundles.append({
            "file": bundle.name,
            "bytes": bundle.stat().st_size,
            "sha256": sha256(bundle),
            "candidate_archives": len(current),
            "members": [
                {"name": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)}
                for p in current
            ],
        })
        current = []
        current_bytes = 0

    for p in files:
        size = p.stat().st_size
        if current and current_bytes + size > args.max_bytes:
            flush()
        current.append(p)
        current_bytes += size
    flush()

    manifest = {
        "contract": "DCE_SINGLE_WRITER_RELEASE_BUNDLE_V1",
        "candidate_archives": len(files),
        "bundle_count": len(bundles),
        "max_target_bytes": args.max_bytes,
        "bundles": bundles,
    }
    manifest_path = out / "dce-canonical-packs-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "candidate_archives": len(files),
        "bundle_count": len(bundles),
        "total_source_bytes": sum(p.stat().st_size for p in files),
        "total_bundle_bytes": sum(b["bytes"] for b in bundles),
        "manifest": str(manifest_path),
    }, indent=2))


if __name__ == "__main__":
    main()
