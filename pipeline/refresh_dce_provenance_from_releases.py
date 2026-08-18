#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import dce_evidence_quality
import extract_corpus
import extract_gates


def load(path: Path, default=None):
    try:
        obj = json.loads(path.read_text(encoding='utf-8', errors='replace'))
        return obj
    except Exception:
        return {} if default is None else default


def run(cmd, *, check=True):
    return subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def gh_repo_args() -> list[str]:
    repo = str(os.getenv('GITHUB_REPOSITORY') or '').strip()
    return ['--repo', repo] if repo else []


def download_workflow_artifact(run_id: int, artifact_name: str, dest: Path) -> Path:
    """Download one exact shard artifact from the DCE workflow run.

    DCE Fanout uses the workflow run id as the durable DCE run id and uploads
    `candidate-<shard>` after extraction/adjudication. This is the most direct
    immutable source for legacy provenance because it survives even when the
    aggregate canonical release bundle was not published.
    """
    if not artifact_name:
        raise RuntimeError('workflow artifact name missing')
    marker = dest / '.complete'
    if marker.exists():
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ['gh', 'run', 'download', str(run_id), '-n', artifact_name, '-D', str(dest), *gh_repo_args()]
    cp = run(cmd, check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"workflow artifact download failed rc={cp.returncode}: {(cp.stderr or '')[-600:]}")
    marker.write_text('ok\n', encoding='utf-8')
    return dest


def download_release_asset(tag: str, name: str, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / name
    if path.exists() and path.stat().st_size:
        return path
    cmd = ['gh', 'release', 'download', tag, '--pattern', name, '--dir', str(dest), '--clobber', *gh_repo_args()]
    cp = run(cmd, check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"release asset download failed {tag}/{name} rc={cp.returncode}: {(cp.stderr or '')[-600:]}")
    if not path.exists():
        raise RuntimeError(f'missing downloaded asset {tag}/{name}')
    return path


def find_bundle(manifest: dict, archive_name: str) -> str | None:
    for bundle in manifest.get('bundles') or []:
        if not isinstance(bundle, dict):
            continue
        for member in bundle.get('members') or []:
            if isinstance(member, dict) and str(member.get('name') or '') == archive_name:
                return str(bundle.get('file') or '') or None
    return None


def safe_extract(tf: tarfile.TarFile, target: Path, members=None):
    target = target.resolve()
    chosen = members if members is not None else tf.getmembers()
    for member in chosen:
        dest = (target / member.name).resolve()
        if target not in dest.parents and dest != target:
            raise RuntimeError(f'unsafe archive path: {member.name}')
    tf.extractall(target, members=chosen)


def stage_candidate_from_release(bundle_path: Path, archive_name: str, root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, 'r') as outer:
        member = outer.getmember(archive_name)
        safe_extract(outer, root, [member])
    candidate_archive = root / archive_name
    candidate_root = root / 'candidate'
    candidate_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(candidate_archive, 'r:gz') as inner:
        safe_extract(inner, candidate_root)
    prepare_candidate_root(candidate_root)
    return candidate_root


def candidate_id_from_file(path: Path) -> str:
    obj = load(path, {})
    if not isinstance(obj, dict):
        return ''
    return str(obj.get('candidate_id') or obj.get('canonical_notice_id') or '').strip()


def find_candidate_root(artifact_root: Path, candidate_id: str) -> Path | None:
    """Locate the exact candidate directory inside one worker artifact."""
    matches: list[Path] = []
    for name in ('candidate.json', 'manifest.json'):
        for path in artifact_root.rglob(name):
            cid = candidate_id_from_file(path)
            if cid == candidate_id:
                matches.append(path.parent)
    if matches:
        # Prefer a root that already contains the worker's downloaded files.
        matches.sort(key=lambda p: (int((p / 'files').is_dir() or (p / 'originals').is_dir()), len(p.parts)), reverse=True)
        return matches[0]

    # Some old worker artifacts omitted candidate.json at nested level but still
    # contained a single candidate root. Accept it only when unambiguous.
    plausible = []
    for manifest in artifact_root.rglob('manifest.json'):
        parent = manifest.parent
        if (parent / 'files').is_dir() or (parent / 'originals').is_dir() or (parent / 'corpus.txt').exists():
            plausible.append(parent)
    unique = []
    seen = set()
    for p in plausible:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique[0] if len(unique) == 1 else None


def prepare_candidate_root(root: Path) -> None:
    files = root / 'files'
    originals = root / 'originals'
    files.mkdir(parents=True, exist_ok=True)
    if originals.exists():
        for p in originals.rglob('*'):
            if not p.is_file():
                continue
            rel = p.relative_to(originals)
            dest = files / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(p, dest)


def canonical_evidence(categories: dict):
    out = {}
    for gate in extract_gates.CANONICAL_PATTERNS:
        vals = categories.get(gate)
        if isinstance(vals, list):
            out[gate] = vals
    return out


def rebuild_override(root: Path, item: dict, *, transport: str, locator: dict) -> tuple[dict, dict]:
    prepare_candidate_root(root)
    files = root / 'files'
    if not files.exists() or not any(p.is_file() for p in files.rglob('*')):
        raise RuntimeError('candidate artifact contains no original/downloaded files to re-extract')

    extract_corpus.process_candidate(root)
    quality = dce_evidence_quality.classify_candidate(root)
    (root / 'evidence_quality.json').write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding='utf-8')
    extract_gates.process(root)
    gates = load(root / 'gate_snippets.json', {})
    docs = load(root / 'document_index.json', [])
    prov = gates.get('snippet_provenance') if isinstance(gates.get('snippet_provenance'), dict) else {}
    cid = str(item.get('candidate_id') or '')
    run_id = int(item.get('dce_run_id'))
    override = {
        'candidate_id': cid,
        'source_dce_run_id': run_id,
        'source_shard': item.get('source_shard'),
        'refreshed_at': datetime.now(timezone.utc).isoformat(),
        'provenance_transport': transport,
        'provenance_locator': locator,
        'evidence_by_gate': canonical_evidence(gates.get('categories') or {}),
        'evidence_quality_summary': quality,
        'evidence_provenance_summary': prov,
        'document_count': len(docs) if isinstance(docs, list) else 0,
        'documents_with_source_url': sum(1 for d in docs if isinstance(d, dict) and d.get('source_url')) if isinstance(docs, list) else 0,
        'policy': 'Re-extracted only from immutable DCE worker/canonical artifacts for the exact candidate and source run. This override changes evidence provenance/presentation only; it is not a new procurement verdict.',
    }
    summary = {
        'candidate_id': cid,
        'source_dce_run_id': run_id,
        'source_shard': item.get('source_shard'),
        'transport': transport,
        'attributed': int(prov.get('attributed') or 0),
        'unattributed': int(prov.get('unattributed') or 0),
        'documents': override['document_count'],
        'documents_with_source_url': override['documents_with_source_url'],
    }
    return override, summary


def release_fallback(item: dict, temp: Path, cache: dict) -> tuple[Path, dict]:
    tag = str(item.get('release_tag') or f"dce-harvest-{item.get('dce_run_id')}")
    archive = str(item.get('archive_name') or '')
    release_dir = temp / 'releases' / tag
    manifest_key = (tag, 'manifest')
    if manifest_key not in cache:
        manifest_path = download_release_asset(tag, 'dce-canonical-packs-manifest.json', release_dir)
        cache[manifest_key] = load(manifest_path, {})
    manifest = cache[manifest_key]
    bundle = find_bundle(manifest, archive)
    if not bundle:
        raise RuntimeError('candidate archive not found in canonical release manifest')
    bundle_key = (tag, bundle)
    if bundle_key not in cache:
        cache[bundle_key] = download_release_asset(tag, bundle, release_dir)
    work = temp / 'release-work' / str(item.get('dce_run_id')) / str(item.get('candidate_id')).replace('/', '_').replace(':', '_')
    root = stage_candidate_from_release(cache[bundle_key], archive, work)
    return root, {'release_tag': tag, 'archive_name': archive, 'bundle_asset': bundle}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', default='control/gpt_provenance_refresh_plan.json')
    ap.add_argument('--existing', default='control/gpt_provenance_overrides.json')
    ap.add_argument('--out', default='control/gpt_provenance_overrides.json')
    args = ap.parse_args()
    plan = load(Path(args.plan), {})
    existing = load(Path(args.existing), {})
    overrides = {str(k): v for k, v in (existing.get('overrides') or {}).items() if isinstance(v, dict)}
    items = [x for x in plan.get('items') or [] if isinstance(x, dict)]
    refreshed = []
    failures = []

    with tempfile.TemporaryDirectory(prefix='dce-provenance-refresh-') as td:
        temp = Path(td)
        artifact_cache: dict[tuple[int, str], Path] = {}
        release_cache: dict = {}
        for item in items:
            cid = str(item.get('candidate_id') or '')
            run_id = int(item.get('dce_run_id'))
            shard = item.get('source_shard')
            artifact_name = str(item.get('workflow_artifact_name') or '')
            artifact_error = None

            # Preferred path: exact immutable worker artifact from the DCE run.
            if artifact_name and shard is not None:
                try:
                    cache_key = (run_id, artifact_name)
                    if cache_key not in artifact_cache:
                        dest = temp / 'workflow-artifacts' / str(run_id) / artifact_name
                        artifact_cache[cache_key] = download_workflow_artifact(run_id, artifact_name, dest)
                    artifact_root = artifact_cache[cache_key]
                    root = find_candidate_root(artifact_root, cid)
                    if root is None:
                        raise RuntimeError(f'exact candidate root not found inside workflow artifact {artifact_name}')
                    override, summary = rebuild_override(
                        root,
                        item,
                        transport='WORKFLOW_ARTIFACT',
                        locator={'workflow_run_id': run_id, 'artifact_name': artifact_name, 'source_shard': shard},
                    )
                    overrides[cid] = override
                    refreshed.append(summary)
                    continue
                except Exception as exc:
                    artifact_error = repr(exc)

            # Fallback for older runs whose workflow artifacts may have expired.
            try:
                root, locator = release_fallback(item, temp, release_cache)
                override, summary = rebuild_override(root, item, transport='CANONICAL_RELEASE_BUNDLE', locator=locator)
                overrides[cid] = override
                refreshed.append(summary)
            except Exception as exc:
                failures.append({
                    'candidate_id': cid,
                    'source_dce_run_id': run_id,
                    'source_shard': shard,
                    'workflow_artifact_error': artifact_error,
                    'release_fallback_error': repr(exc),
                })

    payload = {
        'schema': 'GPT_DCE_PROVENANCE_OVERRIDES_V2_ARTIFACT_FIRST',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'override_count': len(overrides),
        'refreshed_this_run': refreshed,
        'failures_this_run': failures,
        'overrides': overrides,
        'contract': 'Persistent evidence-provenance overlay reconstructed from exact immutable DCE workflow shard artifacts first, canonical release bundles second. Overrides apply only to exact candidate+source-run and never change ranking, eligibility or verdict.',
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'overrides': len(overrides), 'refreshed': len(refreshed), 'failures': len(failures)}, indent=2))


if __name__ == '__main__':
    main()
