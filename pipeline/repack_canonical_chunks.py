from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from collections import defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def add_tree(zf: zipfile.ZipFile, root: Path, path: Path) -> None:
    if path.is_file():
        zf.write(path, path.relative_to(root))
        return
    for p in path.rglob('*'):
        if p.is_file():
            zf.write(p, p.relative_to(root))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='source')
    ap.add_argument('--out', default='canonical_chunks')
    ap.add_argument('--chunks', type=int, default=5)
    ap.add_argument('--source-artifact-id', required=True)
    ap.add_argument('--source-artifact-sha256', default='')
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    groups = []
    dce = root / 'dce-artifacts'
    if dce.exists():
        for child in dce.iterdir():
            groups.append((f'dce-artifacts/{child.name}', child, dir_size(child)))
    agg = root / 'dce-aggregate'
    if agg.exists():
        groups.append(('dce-aggregate', agg, dir_size(agg)))

    # Greedy balance on uncompressed bytes. Each candidate remains atomic.
    bins = [{'bytes': 0, 'groups': []} for _ in range(max(1, args.chunks))]
    for name, path, size in sorted(groups, key=lambda x: x[2], reverse=True):
        b = min(bins, key=lambda x: x['bytes'])
        b['groups'].append((name, path, size))
        b['bytes'] += size

    manifest = {
        'source_artifact_id': str(args.source_artifact_id),
        'source_artifact_sha256': args.source_artifact_sha256 or None,
        'chunk_count': len(bins),
        'chunks': [],
        'coverage': [],
    }

    for idx, b in enumerate(bins):
        chunk_path = out / f'canonical_chunk_{idx:02d}.zip'
        with zipfile.ZipFile(chunk_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for name, path, size in b['groups']:
                add_tree(zf, root, path)
                manifest['coverage'].append({'group': name, 'chunk': idx, 'uncompressed_bytes': size})
        manifest['chunks'].append({
            'chunk': idx,
            'file': chunk_path.name,
            'size_bytes': chunk_path.stat().st_size,
            'sha256': sha256(chunk_path),
            'groups': [name for name, _, _ in b['groups']],
            'uncompressed_bytes': b['bytes'],
        })

    # Coverage integrity: every top-level candidate/aggregate group exactly once.
    expected = sorted(name for name, _, _ in groups)
    covered = sorted(x['group'] for x in manifest['coverage'])
    manifest['coverage_ok'] = expected == covered and len(covered) == len(set(covered))
    manifest['expected_group_count'] = len(expected)
    if not manifest['coverage_ok']:
        raise SystemExit('Canonical chunk coverage failure')

    (out / 'canonical_manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
