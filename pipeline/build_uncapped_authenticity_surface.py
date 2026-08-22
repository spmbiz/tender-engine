from __future__ import annotations

import argparse, json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SUPPORTED = {
    'IRELAND': lambda cid, portal: portal == 'IRELAND_ETENDERS' or cid.upper().startswith('IE:'),
    'ZA_ETENDERS': lambda cid, portal: portal == 'ZA_ETENDERS' and cid.upper().startswith('ZA_ETENDERS_OCDS:OCDS-9T57FA-'),
    'ESTONIA': lambda cid, portal: portal == 'EE_RHR' or cid.upper().startswith('EE-RHR:'),
}


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--index',default='control/gpt_review_index.json')
    ap.add_argument('--out',default='control/gpt_auth_uncapped.json')
    ap.add_argument('--supported-out',default='control/gpt_auth_supported_retry_pool.jsonl')
    args=ap.parse_args()
    idx=json.loads(Path(args.index).read_text(encoding='utf-8'))
    rows=[x for x in (idx.get('items') or []) if isinstance(x,dict) and str(x.get('review_stage') or '').upper()=='DCE_AUTHENTICITY' and x.get('candidate_id')]
    seen=set(); items=[]; by_portal=Counter(); by_source=Counter(); by_reason=Counter(); by_pair=Counter(); supported=[]
    for r in rows:
        cid=str(r.get('candidate_id') or '').strip()
        key=cid.casefold()
        if not cid or key in seen: continue
        seen.add(key)
        portal=str(r.get('portal') or r.get('source') or '').upper()
        source='UNSUPPORTED'
        for name,fn in SUPPORTED.items():
            if fn(cid,portal): source=name; break
        reason=str(r.get('dce_authenticity_reason') or r.get('authenticity_reason') or r.get('review_reason') or r.get('content_quality') or 'UNKNOWN')
        run=int(r.get('source_dce_run_id') or 0)
        shard=int(r.get('source_shard') or 0)
        out={
            'candidate_id':cid,'title':r.get('title'),'buyer':r.get('buyer'),'portal':r.get('portal'),'notice_url':r.get('notice_url'),
            'deadline':r.get('deadline'),'estimated_value':r.get('estimated_value'),'currency':r.get('currency'),
            'spm_fit_band':r.get('spm_fit_band'),'spm_post_dce_score':r.get('spm_post_dce_score'),'spm_fit_reasons':r.get('spm_fit_reasons') or [],
            'source_dce_run_id':run or None,'source_shard':shard,'auth_retry_source':source,'auth_reason':reason,
        }
        items.append(out); by_portal[portal or 'UNKNOWN']+=1; by_source[source]+=1; by_reason[reason]+=1; by_pair[f'{run}:{shard}']+=1
        if source!='UNSUPPORTED': supported.append(out)
    expected=int(((idx.get('counts') or {}).get('by_stage') or {}).get('DCE_AUTHENTICITY') or len(items))
    if len(items)!=expected:
        raise SystemExit(f'auth conservation fail items={len(items)} expected={expected}')
    payload={
        'schema':'GPT_DCE_AUTHENTICITY_UNCAPPED_V1','generated_at':datetime.now(timezone.utc).isoformat(),
        'source_index_updated_at':idx.get('updated_at'),'count':len(items),'supported_exact_retry_count':len(supported),'unsupported_count':len(items)-len(supported),
        'by_portal':dict(by_portal),'by_retry_source':dict(by_source),'by_reason':dict(by_reason),'unique_run_shard_pairs':len(by_pair),
        'items':items,
        'contract':'Every durable DCE_AUTHENTICITY row is materialized. This surface never creates GREEN; supported exact-ID sources may be replayed under the existing cooldown/throttle, unsupported rows remain explicit unresolved work rather than disappearing behind the hot window.'
    }
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with Path(args.supported_out).open('w',encoding='utf-8') as f:
        for r in supported: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps({k:payload[k] for k in ('count','supported_exact_retry_count','unsupported_count','unique_run_shard_pairs','by_retry_source')},indent=2))

if __name__=='__main__': main()
