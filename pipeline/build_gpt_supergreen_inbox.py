from __future__ import annotations
import argparse,json
from datetime import date,datetime,timezone
from pathlib import Path
from typing import Any


def load_json(path: Path)->dict[str,Any]:
    if not path.exists() or not path.read_text(encoding='utf-8',errors='replace').strip(): return {}
    try:
        x=json.loads(path.read_text(encoding='utf-8',errors='replace')); return x if isinstance(x,dict) else {}
    except Exception:return {}

def load_jsonl(paths):
    out=[]
    for p in paths:
        if not Path(p).exists(): continue
        for line in Path(p).read_text(encoding='utf-8',errors='replace').splitlines():
            if line.strip():
                try:x=json.loads(line)
                except Exception:continue
                if isinstance(x,dict):out.append(x)
    return out

def key(r): return str(r.get('candidate_id') or '').strip().casefold()
def open_deadline(r):
    v=str(r.get('deadline') or '').strip()
    if not v:return True
    try:return date.fromisoformat(v[:10])>=datetime.now(timezone.utc).date()
    except Exception:return True

def rank(r):
    action={'FINAL_REVIEW_NOW':4,'REVIEW_IF_CAPACITY':3,'NEED_MORE_DCE':2,'DROP_OR_PARTNER':1,'DROP_EXPIRED':0}.get(str(r.get('recommended_gpt_action')),0)
    return (action,int(r.get('gpt_priority_score') or 0),int(bool(r.get('gate_readiness'))),int(r.get('evidence_gate_coverage') or 0),str(r.get('candidate_id') or ''))
def user_inbox_eligible(r):
    if not isinstance(r,dict) or not key(r) or not open_deadline(r): return False
    action=str(r.get('recommended_gpt_action') or '')
    if action=='FINAL_REVIEW_NOW':
        return bool(r.get('native_spm_core')) and int(r.get('evidence_gate_coverage') or 0)>0 and int(r.get('gpt_priority_score') or 0)>=60
    if action=='REVIEW_IF_CAPACITY':
        return bool(r.get('native_spm_core')) and not bool(r.get('obvious_noncore_scope')) and int(r.get('evidence_gate_coverage') or 0)>0 and int(r.get('gpt_priority_score') or 0)>=50
    return False

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--triage',action='append',default=[]);ap.add_argument('--existing');ap.add_argument('--final-bank');ap.add_argument('--out',required=True);ap.add_argument('--max-items',type=int,default=40);ap.add_argument('--source-run',required=True);args=ap.parse_args()
    existing=load_json(Path(args.existing)) if args.existing else {}
    final=load_json(Path(args.final_bank)) if args.final_bank else {}
    resolved={key(x) for x in final.get('items',[]) if isinstance(x,dict) and key(x)}
    merged={}
    for r in existing.get('pending_final_review',[]) or []:
        if user_inbox_eligible(r) and key(r) not in resolved: merged[key(r)]=r
    for r in load_jsonl(args.triage):
        if key(r) in resolved or not user_inbox_eligible(r): continue
        cur=merged.get(key(r))
        if cur is None or rank(r)>=rank(cur): merged[key(r)]=r
    pending=sorted(merged.values(),key=rank,reverse=True)[:max(0,args.max_items)]
    confirmed=[x for x in (final.get('items') or []) if isinstance(x,dict) and open_deadline(x) and str(x.get('classification') or '') in {'FINAL_SUPER_GREEN','GREEN','YELLOW','RED'}]
    confirmed.sort(key=lambda r:(str(r.get('classification') or '')=='FINAL_SUPER_GREEN',int(r.get('final_score') or 0)),reverse=True)
    payload={
      'schema':'GPT_INSTANT_SUPERGREEN_INBOX_V2','updated_at':datetime.now(timezone.utc).isoformat(),'latest_source_dce_run_id':int(args.source_run) if str(args.source_run).isdigit() else args.source_run,
      'confirmed_supergreens':confirmed,'pending_final_review':pending,
      'counts':{'confirmed_supergreens':sum(str(x.get('classification'))=='FINAL_SUPER_GREEN' for x in confirmed),'confirmed_green_total':sum(str(x.get('classification')) in {'FINAL_SUPER_GREEN','GREEN'} for x in confirmed),'resolved_total':len(confirmed),'pending_final_review':len(pending),'review_now':sum(x.get('recommended_gpt_action')=='FINAL_REVIEW_NOW' for x in pending)},
      'answer_contract':'When the user asks what supergreens exist, read this file first. Report live FINAL_SUPER_GREEN/GREEN verdicts immediately. Then adjudicate pending_final_review rows marked FINAL_REVIEW_NOW from evidence_by_gate. This user-facing inbox intentionally excludes non-core and insufficient Qwen rows. Qwen is pre-read only; missing evidence is UNKNOWN.',
      'finality_rule':'Only GPT Web final adjudication from authoritative DCE evidence may create FINAL_SUPER_GREEN. Qwen never does.',
    }
    Path(args.out).parent.mkdir(parents=True,exist_ok=True);Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(payload['counts'],indent=2))
if __name__=='__main__':main()
