from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

METADATA_FILES = {
    "candidate.json",
    "manifest.json",
    "ted_resolution.json",
    "document_index.json",
    "corpus.txt",
    "gate_snippets.json",
    "portal_page.txt",
}
ROOT_FILES = {"batch_results.json", "batch_summary.json"}
MAX_RELEASE_ASSET_BYTES = 1_900_000_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def slugify(value: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:120]


def selected_originals(candidate_root: Path, manifest: dict) -> list[Path]:
    files_root = candidate_root / "files"
    out: list[Path] = []
    seen: set[Path] = set()
    for rec in manifest.get("files") or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or "").strip()
        if not name:
            continue
        p = files_root / Path(name).name
        if p.is_file() and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def add_file(tar: tarfile.TarFile, path: Path, arcname: str, inventory: list[dict], role: str):
    tar.add(path, arcname=arcname, recursive=False)
    inventory.append(
        {
            "path": arcname,
            "role": role,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    )


def build_candidate_pack(candidate_root: Path, out_dir: Path) -> dict:
    manifest_path = candidate_root / "manifest.json"
    manifest = load_json(manifest_path) or {}
    cid = str(manifest.get("candidate_id") or candidate_root.name)
    archive = out_dir / f"candidate-{slugify(cid)}.tar.gz"
    inventory: list[dict] = []
    originals = selected_originals(candidate_root, manifest)

    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for name in sorted(METADATA_FILES):
            p = candidate_root / name
            if p.is_file():
                add_file(tar, p, name, inventory, "metadata_or_extracted_evidence")
        for p in originals:
            add_file(tar, p, str(Path("originals") / p.name), inventory, "original_download")

        payload = {
            "contract": "CANONICAL_DCE_RELEASE_PACK_V1",
            "candidate_id": cid,
            "original_download_count": len(originals),
            "inventory_count": len(inventory),
            "inventory": inventory,
            "note": "Original downloaded procurement files + normalized evidence. Recursive unpack duplicates excluded because reconstructible from originals.",
        }
        raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo("_canonical_pack_manifest.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))

    if archive.stat().st_size >= MAX_RELEASE_ASSET_BYTES:
        raise RuntimeError(f"Canonical candidate asset exceeds safe GitHub Release limit: {archive} {archive.stat().st_size}")
    return {
        "candidate_id": cid,
        "archive": str(archive),
        "archive_name": archive.name,
        "archive_size": archive.stat().st_size,
        "archive_sha256": sha256_file(archive),
        "original_download_count": len(originals),
        "inventory_count": len(inventory),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    ap.add_argument("--out-dir", default="durable")
    args = ap.parse_args()

    root = Path(args.root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_roots = sorted(set(p.parent for p in root.rglob("manifest.json")))
    packs = [build_candidate_pack(candidate_root, out_dir) for candidate_root in candidate_roots]

    batch_payload = {}
    for name in sorted(ROOT_FILES):
        p = root / name
        if p.is_file():
            batch_payload[name] = load_json(p)
    index = {
        "contract": "CANONICAL_DCE_RELEASE_INDEX_V1",
        "candidate_count": len(packs),
        "original_download_count": sum(p["original_download_count"] for p in packs),
        "total_archive_bytes": sum(p["archive_size"] for p in packs),
        "packs": packs,
        "batch": batch_payload,
    }
    index_path = out_dir / "canonical_index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(index, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
