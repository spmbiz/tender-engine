#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE_RULES = {
    "IRELAND": {
        "queue": "queues/ireland_auth_retry_router.jsonl",
        "match": lambda row, cid, portal: portal == "IRELAND_ETENDERS" or cid.upper().startswith("IE:"),
        "lane": "IRELAND_AUTHENTICITY_EXACT_ID_RETRY",
    },
    "ZA_ETENDERS": {
        "queue": "queues/za_auth_retry_router.jsonl",
        "match": lambda row, cid, portal: portal == "ZA_ETENDERS" and cid.upper().startswith("ZA_ETENDERS_OCDS:OCDS-9T57FA-"),
        "lane": "ZA_ETENDERS_AUTHENTICITY_EXACT_OCID_RETRY",
    },
    "ESTONIA": {
        "queue": "queues/estonia_auth_retry_router.jsonl",
        "match": lambda row, cid, portal: portal == "EE_RHR" or cid.upper().startswith("EE-RHR:"),
        "lane": "ESTONIA_AUTHENTICITY_EXACT_ID_RETRY",
    },
}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def rows(payload):
    if not isinstance(payload, dict): return []
    for key in ("review_queue", "pending_final_review", "items", "pending"):
        value=payload.get(key)
        if isinstance(value,list): return [x for x in value if isinstance(x,dict)]
    return []


def authenticity_pending(row):
    stage=str(row.get("review_stage") or row.get("stage") or row.get("review_lane") or "").upper()
    return "DCE_AUTHENTICITY" in stage or bool(row.get("dce_authenticity_review_required"))


def parse_dt(value):
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--inbox",default="control/gpt_supergreen_inbox.json")
    ap.add_argument("--state",default="control/authenticity_retry_router_state.json")
    ap.add_argument("--plan",default="control/authenticity_retry_router_plan.json")
    ap.add_argument("--limit-per-source",type=int,default=12)
    ap.add_argument("--max-attempts",type=int,default=2)
    ap.add_argument("--cooldown-days",type=int,default=7)
    args=ap.parse_args()
    inbox=load(Path(args.inbox),{})
    state=load(Path(args.state),{})
    records=state.get("records") if isinstance(state.get("records"),dict) else {}
    now=datetime.now(timezone.utc)
    cutoff=now-timedelta(days=max(1,args.cooldown_days))
    selected={name:[] for name in SOURCE_RULES}
    blocked={"cooldown":0,"attempt_cap":0,"unsupported":0}
    seen=set()
    for row in rows(inbox):
        if not authenticity_pending(row): continue
        cid=str(row.get("candidate_id") or "").strip()
        portal=str(row.get("portal") or row.get("source") or "").upper()
        if not cid or cid in seen: continue
        source=None
        for name,rule in SOURCE_RULES.items():
            if rule["match"](row,cid,portal): source=name; break
        if not source:
            blocked["unsupported"]+=1; continue
        rec=records.get(cid) if isinstance(records.get(cid),dict) else {}
        attempts=int(rec.get("attempts") or 0)
        if attempts>=max(1,args.max_attempts):
            blocked["attempt_cap"]+=1; continue
        last=parse_dt(rec.get("last_dispatched_at"))
        if last and last>cutoff:
            blocked["cooldown"]+=1; continue
        if len(selected[source])>=max(1,args.limit_per_source): continue
        seen.add(cid)
        selected[source].append({
            "candidate_id":cid,
            "selection_lane":SOURCE_RULES[source]["lane"],
            "selection_reason":"stateful exact-ID replay through canonical DCE resolver; evidence-quality and final guards remain authoritative",
            "prior_attempts":attempts,
            "source_dce_run_id":row.get("source_dce_run_id"),
        })
    for source,items in selected.items():
        q=Path(SOURCE_RULES[source]["queue"]);q.parent.mkdir(parents=True,exist_ok=True)
        q.write_text("".join(json.dumps({k:v for k,v in item.items() if k in {'candidate_id','selection_lane','selection_reason'}},ensure_ascii=False,separators=(",",":"))+"\n" for item in items),encoding="utf-8")
    plan={
        "schema":"AUTHENTICITY_RETRY_ROUTER_PLAN_V1",
        "generated_at":now.isoformat(),
        "selected_counts":{k:len(v) for k,v in selected.items()},
        "selected":selected,
        "queue_paths":{k:v["queue"] for k,v in SOURCE_RULES.items()},
        "blocked":blocked,
        "policy":{"supported_sources":list(SOURCE_RULES),"max_attempts":max(1,args.max_attempts),"cooldown_days":max(1,args.cooldown_days),"exact_candidate_ids_only":True,"creates_green":False,"unknown_never_pass":True},
    }
    p=Path(args.plan);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"selected_counts":plan["selected_counts"],"blocked":blocked},indent=2))

if __name__=="__main__":main()
