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
        obj=json.loads(path.read_text(encoding='utf-8'))
        return obj
    except Exception:
        return {} if default is None else default


def run(cmd):
    subprocess.run(cmd,check=True)


def download_release_asset(tag: str, name: str, dest: Path):
    dest.mkdir(parents=True,exist_ok=True)
    path=dest/name
    if path.exists() and path.stat().st_size:
        return path
    run(['gh','release','download',tag,'--pattern',name,'--dir',str(dest),'--clobber'])
    if not path.exists():
        raise RuntimeError(f'missing downloaded asset {tag}/{name}')
    return path


def find_bundle(manifest: dict, archive_name: str) -> str | None:
    for bundle in manifest.get('bundles') or []:
        if not isinstance(bundle,dict): continue
        for member in bundle.get('members') or []:
            if isinstance(member,dict) and str(member.get('name') or '')==archive_name:
                return str(bundle.get('file') or '') or None
    return None


def safe_extract(tf: tarfile.TarFile, target: Path, members=None):
    target=target.resolve()
    chosen=members if members is not None else tf.getmembers()
    for member in chosen:
        dest=(target/member.name).resolve()
        if target not in dest.parents and dest!=target:
            raise RuntimeError(f'unsafe archive path: {member.name}')
    tf.extractall(target,members=chosen)


def stage_candidate(bundle_path: Path, archive_name: str, root: Path):
    root.mkdir(parents=True,exist_ok=True)
    with tarfile.open(bundle_path,'r') as outer:
        member=outer.getmember(archive_name)
        safe_extract(outer,root,[member])
    candidate_archive=root/archive_name
    candidate_root=root/'candidate'
    candidate_root.mkdir(parents=True,exist_ok=True)
    with tarfile.open(candidate_archive,'r:gz') as inner:
        safe_extract(inner,candidate_root)
    originals=candidate_root/'originals'
    files=candidate_root/'files'
    files.mkdir(exist_ok=True)
    if originals.exists():
        for p in originals.iterdir():
            if p.is_file():
                shutil.copy2(p,files/p.name)
    return candidate_root


def canonical_evidence(categories: dict):
    out={}
    for gate in extract_gates.CANONICAL_PATTERNS:
        vals=categories.get(gate)
        if isinstance(vals,list): out[gate]=vals
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--plan',default='control/gpt_provenance_refresh_plan.json')
    ap.add_argument('--existing',default='control/gpt_provenance_overrides.json')
    ap.add_argument('--out',default='control/gpt_provenance_overrides.json')
    args=ap.parse_args()
    plan=load(Path(args.plan),{})
    existing=load(Path(args.existing),{})
    overrides={str(k):v for k,v in (existing.get('overrides') or {}).items() if isinstance(v,dict)}
    items=[x for x in plan.get('items') or [] if isinstance(x,dict)]
    by_release={}
    for item in items: by_release.setdefault(str(item['release_tag']),[]).append(item)
    refreshed=[]; failures=[]
    with tempfile.TemporaryDirectory(prefix='dce-provenance-refresh-') as td:
        temp=Path(td)
        for tag, group in by_release.items():
            release_dir=temp/'releases'/tag
            try:
                manifest_path=download_release_asset(tag,'dce-canonical-packs-manifest.json',release_dir)
                manifest=load(manifest_path,{})
            except Exception as exc:
                for item in group: failures.append({'candidate_id':item.get('candidate_id'),'release_tag':tag,'error':f'manifest:{exc!r}'})
                continue
            bundles={}
            for item in group:
                cid=str(item.get('candidate_id') or '')
                archive=str(item.get('archive_name') or '')
                bundle=find_bundle(manifest,archive)
                if not bundle:
                    failures.append({'candidate_id':cid,'release_tag':tag,'error':'candidate archive not found in release manifest'})
                    continue
                try:
                    if bundle not in bundles:
                        bundles[bundle]=download_release_asset(tag,bundle,release_dir)
                    work=temp/'work'/str(item.get('dce_run_id'))/cid.replace('/','_').replace(':','_')
                    root=stage_candidate(bundles[bundle],archive,work)
                    extract_corpus.process_candidate(root)
                    quality=dce_evidence_quality.classify_candidate(root)
                    (root/'evidence_quality.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
                    extract_gates.process(root)
                    gates=load(root/'gate_snippets.json',{})
                    docs=load(root/'document_index.json',[])
                    prov=gates.get('snippet_provenance') if isinstance(gates.get('snippet_provenance'),dict) else {}
                    overrides[cid]={
                        'candidate_id':cid,
                        'source_dce_run_id':int(item.get('dce_run_id')),
                        'release_tag':tag,
                        'archive_name':archive,
                        'bundle_asset':bundle,
                        'refreshed_at':datetime.now(timezone.utc).isoformat(),
                        'evidence_by_gate':canonical_evidence(gates.get('categories') or {}),
                        'evidence_quality_summary':quality,
                        'evidence_provenance_summary':prov,
                        'document_count':len(docs) if isinstance(docs,list) else 0,
                        'policy':'Re-extracted from immutable canonical DCE original downloads. This override changes evidence provenance/presentation only; it is not a new procurement verdict.',
                    }
                    refreshed.append({'candidate_id':cid,'source_dce_run_id':item.get('dce_run_id'),'attributed':prov.get('attributed',0),'unattributed':prov.get('unattributed',0),'bundle':bundle})
                except Exception as exc:
                    failures.append({'candidate_id':cid,'release_tag':tag,'error':repr(exc)})
    payload={
        'schema':'GPT_DCE_PROVENANCE_OVERRIDES_V1',
        'updated_at':datetime.now(timezone.utc).isoformat(),
        'override_count':len(overrides),
        'refreshed_this_run':refreshed,
        'failures_this_run':failures,
        'overrides':overrides,
        'contract':'Persistent evidence-provenance overlay reconstructed only from immutable canonical DCE packs. Rebuilds may apply it only to the exact candidate and exact source DCE run.',
    }
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'overrides':len(overrides),'refreshed':len(refreshed),'failures':len(failures)},indent=2))

if __name__=='__main__':main()
