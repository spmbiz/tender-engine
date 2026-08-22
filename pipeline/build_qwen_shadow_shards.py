#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA='QWEN_SHADOW_INPUT_V1'
MANIFEST_SCHEMA='QWEN_SHADOW_SHARD_MANIFEST_V4'
# A 480-row shard at the validated singleton rate stays comfortably inside the
# workflow timeout while amortizing runner/model startup across far more useful
# work. The workflow request remains authoritative and rows not selected remain
# in the canonical residual queue.
DEFAULT_OPERATIONAL_MAX_ROWS_PER_SHARD=480
DEFAULT_FRESH_HOURS=24


def open_text(path:Path,mode:str):
    return gzip.open(path,mode+'t',encoding='utf-8') if path.suffix=='.gz' else path.open(mode,encoding='utf-8')


def iter_rows(path:Path):
    with open_text(path,'r') as fh:
        for raw in fh:
            raw=raw.strip()
            if not raw: continue
            try:r=json.loads(raw)
            except json.JSONDecodeError: continue
            if isinstance(r,dict): yield r


def notice(row):
    n=row.get('notice')
    return n if isinstance(n,dict) else row


def cid(row,n):
    return str(row.get('canonical_notice_id') or n.get('candidate_id') or n.get('notice_id') or n.get('id') or '').strip()


def compact(row:dict[str,Any])->dict[str,Any]:
    n=notice(row); c=cid(row,n)
    keep={
        'candidate_id':c,
        'material_fields_hash':row.get('material_fields_hash'),
        'queue_reason':row.get('queue_reason'),
        'first_seen_at':row.get('first_seen_at'),
        'last_seen_at':row.get('last_seen_at'),
        'source':n.get('source'),
        'source_family':n.get('source_family'),
        'country':n.get('country'),
        'buyer':n.get('buyer'),
        'title':n.get('title'),
        'description':n.get('description'),
        'cpv_or_category':n.get('cpv_or_category'),
        'estimated_value':n.get('estimated_value'),
        'currency':n.get('currency'),
        'publication_date':n.get('publication_date'),
        'deadline':n.get('deadline'),
        'deadline_utc':n.get('deadline_utc'),
        'procedure':n.get('procedure'),
        'lots':n.get('lots'),
        'notice_eligibility':n.get('notice_eligibility'),
        'award_criteria':n.get('award_criteria'),
        'subcontracting':n.get('subcontracting'),
        'urls':n.get('urls'),
        'historical_prior':row.get('historical_prior'),
    }
    return {'schema':SCHEMA,**keep}


def shard_for(candidate_id:str,count:int)->int:
    digest=hashlib.sha256(candidate_id.encode('utf-8')).digest()
    return int.from_bytes(digest[:8],'big')%count


def stable_priority(candidate_id:str)->bytes:
    return hashlib.sha256(('qwen-live:'+candidate_id).encode('utf-8')).digest()


def _parse_ts(value:object):
    if not value:
        return None
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def freshness_rank(row:dict[str,Any],*,now:datetime|None=None,fresh_hours:int=DEFAULT_FRESH_HOURS)->int:
    reason=str(row.get('queue_reason') or '').upper()
    if reason in {'NEW','UPDATED'}:
        return 0
    current=now or datetime.now(timezone.utc)
    first=_parse_ts(row.get('first_seen_at'))
    if first is not None:
        age_hours=(current-first).total_seconds()/3600
        if -1 <= age_hours <= fresh_hours:
            return 1
    return 2


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--out-dir',required=True)
    ap.add_argument('--source-run',required=True)
    ap.add_argument('--shards',type=int,default=32)
    ap.add_argument('--max-rows-per-shard',type=int,default=None,
                    help='Bound derived work per worker; omitted rows remain in the canonical residual queue.')
    ap.add_argument('--manifest-out',required=True)
    a=ap.parse_args()
    if a.shards<1 or a.shards>256: raise SystemExit('shards must be 1..256')

    env_cap=os.environ.get('REQUESTED_PER_SHARD','').strip()
    operational_env=os.environ.get('QWEN_OPERATIONAL_ROWS_PER_SHARD','').strip()
    fresh_env=os.environ.get('QWEN_FRESH_HOURS','').strip()
    try:
        operational_cap=int(operational_env) if operational_env else DEFAULT_OPERATIONAL_MAX_ROWS_PER_SHARD
    except ValueError:
        raise SystemExit(f'invalid QWEN_OPERATIONAL_ROWS_PER_SHARD={operational_env!r}')
    try:
        fresh_hours=int(fresh_env) if fresh_env else DEFAULT_FRESH_HOURS
    except ValueError:
        raise SystemExit(f'invalid QWEN_FRESH_HOURS={fresh_env!r}')
    if operational_cap<1 or operational_cap>10000:
        raise SystemExit('QWEN operational rows per shard must be 1..10000')
    if fresh_hours<1 or fresh_hours>168:
        raise SystemExit('QWEN fresh hours must be 1..168')

    if a.max_rows_per_shard is not None:
        requested_cap=int(a.max_rows_per_shard)
        cap=requested_cap
    elif env_cap:
        try: requested_cap=int(env_cap)
        except ValueError: raise SystemExit(f'invalid REQUESTED_PER_SHARD={env_cap!r}')
        cap=min(requested_cap,operational_cap) if requested_cap>0 else requested_cap
    else:
        requested_cap=0
        cap=0
    if requested_cap<0 or requested_cap>10000: raise SystemExit('requested max rows per shard must be 0..10000')
    if cap<0 or cap>10000: raise SystemExit('max rows per shard must be 0..10000')

    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)
    paths=[out/f'qwen-shadow-{a.source_run}-shard-{i:03d}-of-{a.shards:03d}.jsonl.gz' for i in range(a.shards)]

    buckets=[[] for _ in range(a.shards)]
    total=0; seen=set(); duplicate_ids=0; missing_ids=0
    now=datetime.now(timezone.utc)
    input_freshness=Counter()
    for row in iter_rows(Path(a.input)):
        total+=1; n=notice(row); c=cid(row,n)
        if not c:
            missing_ids+=1; continue
        if c in seen:
            duplicate_ids+=1
            continue
        seen.add(c)
        idx=shard_for(c,a.shards)
        rank=freshness_rank(row,now=now,fresh_hours=fresh_hours)
        input_freshness[rank]+=1
        buckets[idx].append((rank,stable_priority(c),c,row))

    if missing_ids or duplicate_ids:
        raise SystemExit(f'identity invariant failed missing={missing_ids} duplicates={duplicate_ids}')
    if total!=len(seen):
        raise SystemExit(f'row conservation failed total={total} unique={len(seen)}')

    counts=Counter(); selected_ids=set(); selected_freshness=Counter()
    for idx,bucket in enumerate(buckets):
        bucket.sort(key=lambda x:(x[0],x[1],x[2]))
        chosen=bucket if cap==0 else bucket[:cap]
        with open_text(paths[idx],'w') as fh:
            for rank,_,c,row in chosen:
                selected_ids.add(c); counts[idx]+=1; selected_freshness[rank]+=1
                fh.write(json.dumps(compact(row),ensure_ascii=False,separators=(',',':'))+'\n')

    selected=len(selected_ids)
    deferred=total-selected
    if selected!=sum(counts.values()):
        raise SystemExit(f'selected/shard conservation failed selected={selected} shards={sum(counts.values())}')
    if cap and any(counts[i]>cap for i in range(a.shards)):
        raise SystemExit('per-shard bound violated')

    files=[]
    for i,p in enumerate(paths):
        files.append({'shard':i,'path':p.name,'rows':counts[i],'bytes':p.stat().st_size,'sha256':sha256(p)})
    labels={0:'material_new_or_updated',1:'recent_unseen_carryover',2:'historical_backfill'}
    manifest={
        'schema':MANIFEST_SCHEMA,
        'source_run':str(a.source_run),
        'input_rows':total,
        'unique_ids':len(seen),
        'shard_count':a.shards,
        'requested_max_rows_per_shard':requested_cap or None,
        'operational_cap_rows_per_shard':operational_cap,
        'fresh_priority_hours':fresh_hours,
        'max_rows_per_shard':cap or None,
        'selected_rows':selected,
        'sharded_rows':selected,
        'deferred_rows':deferred,
        'freshness_input':{labels[k]:input_freshness[k] for k in labels},
        'freshness_selected':{labels[k]:selected_freshness[k] for k in labels},
        'missing_ids':missing_ids,
        'duplicate_ids':duplicate_ids,
        'assignment':'sha256(candidate_id) first 8 bytes mod shard_count; NEW/UPDATED then recent unseen carryover then stable-hash historical backfill within shard',
        'files':files,
        'safety':{
            'source_residual_unchanged':True,
            'deferred_rows_remain_for_future_passes':True,
            'drops_or_deletes_notices':False,
            'shards_are_derived':True,
            'automatic_rejection_enabled':False,
            'live_requests_clamped_for_bounded_runtime':True,
            'fresh_notices_preempt_historical_backfill':True,
        }
    }
    Path(a.manifest_out).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ('source_run','input_rows','unique_ids','shard_count','requested_max_rows_per_shard','operational_cap_rows_per_shard','fresh_priority_hours','max_rows_per_shard','selected_rows','deferred_rows','freshness_input','freshness_selected','missing_ids','duplicate_ids')},indent=2))

if __name__=='__main__':main()
