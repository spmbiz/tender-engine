#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from durable_dce_pack import slugify

BAND_RANK = {"HOT": 0, "GOOD": 1, "MAYBE": 2, "LOW": 3, "UNKNOWN": 4}


def load(path: Path):
    try:
        obj=json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj,dict) else {}
    except Exception:
        return {}


def needs_refresh(row: dict) -> bool:
    eq=row.get('evidence_quality') if isinstance(row.get('evidence_quality'),dict) else {}
    legacy=int(eq.get('artifact_lookup_required_snippets') or 0)
    all_attr=bool(eq.get('all_compact_snippets_document_attributed'))
    return legacy>0 or not all_attr


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--inbox',default='control/gpt_supergreen_inbox.json')
    ap.add_argument('--out',default='control/gpt_provenance_refresh_plan.json')
    ap.add_argument('--limit',type=int,default=24)
    ap.add_argument('--max-releases',type=int,default=3)
    args=ap.parse_args()
    inbox=load(Path(args.inbox))
    rows=[r for r in inbox.get('review_queue',[]) if isinstance(r,dict)]
    candidates=[]
    for row in rows:
        band=str(row.get('spm_fit_band') or 'UNKNOWN').upper()
        if band not in {'HOT','GOOD','MAYBE'} or not needs_refresh(row):
            continue
        loc=row.get('artifact_locator') if isinstance(row.get('artifact_locator'),dict) else {}
        run=loc.get('dce_run_id') or row.get('source_dce_run_id')
        if not str(run or '').isdigit():
            continue
        cid=str(row.get('candidate_id') or '').strip()
        if not cid:
            continue
        candidates.append({
            'candidate_id':cid,
            'dce_run_id':int(run),
            'release_tag':loc.get('release_tag') or f'dce-harvest-{run}',
            'archive_name':f'candidate-{slugify(cid)}.tar.gz',
            'spm_fit_band':band,
            'score':int(row.get('gpt_priority_score') or row.get('spm_post_dce_score') or row.get('priority_score') or 0),
            'portal':row.get('portal'),
        })
    candidates.sort(key=lambda r:(BAND_RANK.get(r['spm_fit_band'],4),-r['score'],r['candidate_id']))
    by_release=defaultdict(list)
    for row in candidates:
        by_release[row['release_tag']].append(row)
    selected=[]; selected_releases=[]
    # Pick the release containing the best remaining candidate, then amortize the
    # download by taking other useful candidates from that same immutable release.
    remaining=list(candidates)
    while remaining and len(selected)<max(1,args.limit) and len(selected_releases)<max(1,args.max_releases):
        release=remaining[0]['release_tag']
        selected_releases.append(release)
        group=[r for r in remaining if r['release_tag']==release]
        for row in group:
            if len(selected)>=args.limit: break
            selected.append(row)
        picked={r['candidate_id'] for r in group}
        remaining=[r for r in remaining if r['candidate_id'] not in picked]
    payload={
        'schema':'DCE_PROVENANCE_REFRESH_PLAN_V1',
        'source_inbox_updated_at':inbox.get('updated_at'),
        'eligible_legacy_reviews':len(candidates),
        'selected':len(selected),
        'release_count':len(selected_releases),
        'release_tags':selected_releases,
        'items':selected,
        'policy':'HOT/GOOD/MAYBE legacy evidence only; max release downloads bound cost. Re-extraction uses immutable canonical DCE packs and never changes the procurement facts or final verdict.',
    }
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:payload[k] for k in ('eligible_legacy_reviews','selected','release_count','release_tags')},indent=2))

if __name__=='__main__':main()
