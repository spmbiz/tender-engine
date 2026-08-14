from __future__ import annotations

import argparse
import hashlib
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    inventory: list[dict] = []
    candidate_count = 0
    original_download_count = 0

    with tarfile.open(out_path, "w:gz", compresslevel=6) as tar:
        for manifest_path in sorted(root.rglob("manifest.json")):
            candidate_root = manifest_path.parent
            try:
                rel_root = candidate_root.relative_to(root)
            except ValueError:
                continue
            manifest = load_json(manifest_path) or {}
            candidate_count += 1

            for name in sorted(METADATA_FILES):
                p = candidate_root / name
                if p.is_file():
                    add_file(tar, p, str(rel_root / name), inventory, "metadata_or_extracted_evidence")

            for p in selected_originals(candidate_root, manifest):
                original_download_count += 1
                add_file(tar, p, str(rel_root / "originals" / p.name), inventory, "original_download")

        for name in sorted(ROOT_FILES):
            p = root / name
            if p.is_file():
                add_file(tar, p, name, inventory, "batch_metric")

        manifest_payload = {
            "contract": "CANONICAL_DCE_RELEASE_PACK_V1",
            "candidate_count": candidate_count,
            "original_download_count": original_download_count,
            "inventory_count": len(inventory),
            "inventory": inventory,
            "note": "Contains original downloaded procurement files referenced by manifests plus normalized extracted evidence. Recursive unpack duplicates are intentionally excluded because they are reconstructible from originals.",
        }
        manifest_bytes = json.dumps(manifest_payload, indent=2, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo("_canonical_pack_manifest.json")
        info.size = len(manifest_bytes)
        import io
        tar.addfile(info, io.BytesIO(manifest_bytes))

    result = {
        "archive": str(out_path),
        "archive_size": out_path.stat().st_size,
        "archive_sha256": sha256_file(out_path),
        "candidate_count": candidate_count,
        "original_download_count": original_download_count,
        "inventory_count": len(inventory),
    }
    Path(str(out_path) + ".sha256.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
