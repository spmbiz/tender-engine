#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return default


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--plan',default='control/authenticity_retry_router_plan.json')
    ap.add_argument('--state',default='control/authenticity_retry_router_state.json')
    ap.add_argument('--sources',default='IRELAND,ZA_ETENDERS,ESTONIA')
    args=ap.parse_args()
    plan=load(Path(args.plan),{})
    state=load(Path(args.state),{})
    records=state.get('records') if isinstance(state.get('records'),dict) else {}
    allowed={x.strip().upper() for x in args.sources.split(',') if x.strip()}
    now=datetime.now(timezone.utc).isoformat()
    marked=0
    for source,items in (plan.get('selected') or {}).items():
        if str(source).upper() not in allowed or not isinstance(items,list):
            continue
        for item in items:
            if not isinstance(item,dict): continue
            cid=str(item.get('candidate_id') or '').strip()
            if not cid: continue
            old=records.get(cid) if isinstance(records.get(cid),dict) else {}
            records[cid]={
                **old,
                'candidate_id':cid,
                'source':source,
                'attempts':int(old.get('attempts') or 0)+1,
                'last_dispatched_at':now,
                'last_source_dce_run_id':item.get('source_dce_run_id'),
                'last_router_plan_generated_at':plan.get('generated_at'),
            }
            marked+=1
    payload={
        'schema':'AUTHENTICITY_RETRY_ROUTER_STATE_V1',
        'updated_at':now,
        'record_count':len(records),
        'marked_this_run':marked,
        'records':records,
        'contract':'State tracks only dispatch attempts for exact-ID authenticity retries. It never records eligibility or procurement verdicts.',
    }
    p=Path(args.state);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'marked':marked,'record_count':len(records)},indent=2))

if __name__=='__main__':main()
