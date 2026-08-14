from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

CORE_FILES = {
    'candidate.json',
    'manifest.json',
    'ted_resolution.json',
    'document_index.json',
    'corpus.txt',
    'gate_snippets.json',
    'portal_page.txt',
}
ROOT_KEEP = {'batch_results.json', 'batch_summary.json'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='out')
    ap.add_argument('--out', default='canonical-staging')
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    inventory = []
    candidate_count = 0

    for manifest_path in sorted(root.rglob('manifest.json')):
        candidate_root = manifest_path.parent
        try:
            rel = candidate_root.relative_to(root)
        except ValueError:
            continue
        candidate_count += 1
        target = out / rel
        target.mkdir(parents=True, exist_ok=True)

        # Preserve downloaded source files exactly once. Do not persist recursively
        # unpacked duplicates because they are reproducible from these originals.
        files_dir = candidate_root / 'files'
        if files_dir.exists():
            for src in sorted(p for p in files_dir.rglob('*') if p.is_file()):
                copy_file(src, target / 'files' / src.relative_to(files_dir))

        for name in CORE_FILES:
            src = candidate_root / name
            if src.is_file():
                copy_file(src, target / name)

    for name in ROOT_KEEP:
        src = root / name
        if src.is_file():
            copy_file(src, out / name)

    for path in sorted(p for p in out.rglob('*') if p.is_file()):
        if path.name == 'canonical_inventory.json':
            continue
        inventory.append({
            'path': str(path.relative_to(out)).replace('\\', '/'),
            'size_bytes': path.stat().st_size,
            'sha256': sha256(path),
        })

    payload = {
        'candidate_count': candidate_count,
        'file_count': len(inventory),
        'total_bytes': sum(x['size_bytes'] for x in inventory),
        'contract': 'canonical staging preserves original downloaded DCE/source files plus candidate metadata, manifests, route resolution, extracted corpus, document index, gate evidence and portal fallback text; reproducible recursive unpacked copies are intentionally excluded',
        'files': inventory,
    }
    (out / 'canonical_inventory.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in payload.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
