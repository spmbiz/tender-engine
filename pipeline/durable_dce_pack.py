from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

from authority_conflicts import process as process_authority_conflicts
from build_gpt_dce_read_layer import build_candidate_layer

METADATA_FILES = {
    "candidate.json",
    "manifest.json",
    "ted_resolution.json",
    "document_index.json",
    "corpus.txt",
    "evidence_quality.json",
    "gate_snippets.json",
    "authority_conflicts.json",
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


def add_gpt_read_layer(tar: tarfile.TarFile, candidate_root: Path, inventory: list[dict]) -> int:
    gpt_read = candidate_root / "gpt_read"
    if not gpt_read.is_dir():
        return 0
    count = 0
    for path in sorted(gpt_read.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(candidate_root)
        add_file(tar, path, str(rel), inventory, "gpt_read_layer")
        count += 1
    return count


def build_candidate_pack(candidate_root: Path, out_dir: Path) -> dict:
    manifest_path = candidate_root / "manifest.json"
    manifest = load_json(manifest_path) or {}
    evidence = load_json(candidate_root / "evidence_quality.json") or {}
    try:
        authority = process_authority_conflicts(candidate_root)
    except Exception:
        authority = load_json(candidate_root / "authority_conflicts.json") or {}
    cid = str(manifest.get("candidate_id") or candidate_root.name)
    archive = out_dir / f"candidate-{slugify(cid)}.tar.gz"
    inventory: list[dict] = []
    originals = selected_originals(candidate_root, manifest)

    # The Markdown layer is derivative and additive. If it cannot be generated,
    # canonical originals/evidence still pack normally.
    gpt_read_error = None
    try:
        build_candidate_layer(candidate_root)
    except Exception as exc:
        gpt_read_error = repr(exc)

    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for name in sorted(METADATA_FILES):
            p = candidate_root / name
            if p.is_file():
                add_file(tar, p, name, inventory, "metadata_or_extracted_evidence")
        gpt_read_file_count = add_gpt_read_layer(tar, candidate_root, inventory)
        for p in originals:
            add_file(tar, p, str(Path("originals") / p.name), inventory, "original_download")

        deadline = authority.get("deadline") if isinstance(authority, dict) else {}
        payload = {
            "contract": "CANONICAL_DCE_RELEASE_PACK_V4_GPT_READ",
            "candidate_id": cid,
            "original_download_count": len(originals),
            "gpt_read_file_count": gpt_read_file_count,
            "gpt_read_error": gpt_read_error,
            "inventory_count": len(inventory),
            "evidence_quality": evidence.get("content_quality"),
            "gate_readiness": evidence.get("gate_readiness", False),
            "derived_status": evidence.get("derived_status") or manifest.get("status"),
            "deadline_authority_status": deadline.get("status") if isinstance(deadline, dict) else None,
            "deadline_conflict": bool(deadline.get("conflict")) if isinstance(deadline, dict) else False,
            "inventory": inventory,
            "note": "Original downloaded procurement files + normalized evidence + GPT-readable Markdown navigation + evidence-quality verdict + authority-conflict record. Recursive unpack duplicates excluded because reconstructible from originals.",
        }
        raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo("_canonical_pack_manifest.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))

    if archive.stat().st_size >= MAX_RELEASE_ASSET_BYTES:
        raise RuntimeError(f"Canonical candidate asset exceeds safe GitHub Release limit: {archive} {archive.stat().st_size}")
    deadline = authority.get("deadline") if isinstance(authority, dict) else {}
    return {
        "candidate_id": cid,
        "archive": str(archive),
        "archive_name": archive.name,
        "archive_size": archive.stat().st_size,
        "archive_sha256": sha256_file(archive),
        "original_download_count": len(originals),
        "gpt_read_file_count": gpt_read_file_count,
        "gpt_read_error": gpt_read_error,
        "inventory_count": len(inventory),
        "evidence_quality": evidence.get("content_quality"),
        "gate_readiness": evidence.get("gate_readiness", False),
        "derived_status": evidence.get("derived_status") or manifest.get("status"),
        "deadline_authority_status": deadline.get("status") if isinstance(deadline, dict) else None,
        "deadline_conflict": bool(deadline.get("conflict")) if isinstance(deadline, dict) else False,
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
        "contract": "CANONICAL_DCE_RELEASE_INDEX_V4_GPT_READ",
        "candidate_count": len(packs),
        "gate_ready_count": sum(1 for p in packs if p.get("gate_readiness")),
        "gate_blocked_count": sum(1 for p in packs if not p.get("gate_readiness")),
        "deadline_conflict_count": sum(1 for p in packs if p.get("deadline_conflict")),
        "gpt_read_candidate_count": sum(1 for p in packs if p.get("gpt_read_file_count")),
        "gpt_read_file_count": sum(int(p.get("gpt_read_file_count") or 0) for p in packs),
        "gpt_read_error_count": sum(1 for p in packs if p.get("gpt_read_error")),
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
