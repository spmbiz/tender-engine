from __future__ import annotations

import argparse
import base64
import json
import os
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

GREEN_CLASSES = {"FINAL_SUPER_GREEN", "GREEN", "GREEN_PARTNERABLE"}
REVIEW_CLASS = "MODEL_REVIEW_REQUIRED"
CLASS_RANK = {"FINAL_SUPER_GREEN": 4, "GREEN": 3, "GREEN_PARTNERABLE": 2}
RESOLVED_DEADLINE = {"CONSISTENT_NOTICE_DATE_FOUND_IN_DCE", "DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING"}


def utc_now() -> str: return datetime.now(timezone.utc).isoformat()


def load_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text: return []
    if path.suffix.lower() == ".jsonl": return [json.loads(line) for line in text.splitlines() if line.strip()]
    obj = json.loads(text)
    if isinstance(obj, list): return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict) and isinstance(obj.get("items"), list): return [x for x in obj["items"] if isinstance(x, dict)]
    return [obj] if isinstance(obj, dict) else []


def item_key(rec: dict) -> str:
    cid = str(rec.get("candidate_id") or "").strip().casefold()
    return cid or "|".join(str(rec.get(k) or "").strip().casefold() for k in ("title","buyer","notice_url"))


def compact_green(rec: dict, run_id: str, shard: str, published_at: str) -> dict:
    gates = rec.get("gates") or {}; statuses = {str(n):str(i.get("status") or "UNKNOWN").upper() for n,i in gates.items() if isinstance(i,dict)}; resolved={"PASS","PASS_CONDITIONAL","NOT_APPLICABLE"}; cls=str(rec.get("classification") or "").upper()
    return {"candidate_id":rec.get("candidate_id"),"title":rec.get("title"),"buyer":rec.get("buyer"),"portal":rec.get("portal"),"notice_url":rec.get("notice_url"),"deadline":rec.get("deadline"),"estimated_value":rec.get("estimated_value"),"currency":rec.get("currency"),"classification":cls,"final_score":int(rec.get("final_score") or 0),"summary":rec.get("summary"),"content_quality":rec.get("content_quality"),"gate_readiness":bool(rec.get("gate_readiness")),"gate_statuses":statuses,"unresolved_gates":[k for k,v in statuses.items() if v not in resolved],"hard_fail_gates":[k for k,v in statuses.items() if v=="FAIL_HARD"],"authority_conflicts":rec.get("authority_conflicts") or {},"source_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"source_shard":int(shard) if str(shard).isdigit() else shard,"hot_published_at":published_at}


def green_sort_key(rec: dict): return (CLASS_RANK.get(str(rec.get("classification") or "").upper(),-1),int(rec.get("final_score") or 0),str(rec.get("hot_published_at") or ""))


def merge_green(existing: dict, incoming: list[dict], run_id: str, shard: str, max_green: int) -> dict:
    merged={}
    for bucket in ("final_supergreens","greens"):
        for rec in existing.get(bucket) or []:
            if isinstance(rec,dict): merged[item_key(rec)] = rec
    for rec in incoming:
        k=item_key(rec); cur=merged.get(k)
        if cur is None or green_sort_key(rec)>=green_sort_key(cur): merged[k]=rec
    items=sorted(merged.values(),key=green_sort_key,reverse=True); finals=[x for x in items if x.get("classification")=="FINAL_SUPER_GREEN"][:max_green]; greens=[x for x in items if x.get("classification") in {"GREEN","GREEN_PARTNERABLE"}][:max_green]
    source_runs=[]
    for value in [run_id]+list(existing.get("source_runs") or []):
        s=str(value).strip()
        if s and s not in source_runs: source_runs.append(s)
    return {"schema":"SUPERGREEN_HOT_V1","updated_at":utc_now(),"latest_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"latest_shard":int(shard) if str(shard).isdigit() else shard,"source_runs":source_runs[:20],"counts":{"final_supergreen":len(finals),"green_or_partnerable":len(greens)},"final_supergreens":finals,"greens":greens,"rule":"Hot green cache only. FINAL_SUPER_GREEN remains valid only when produced from authoritative DCE evidence and accepted by final_verdict_guard.py. Canonical immutable evidence remains in DCE Release assets."}


def _deadline_info(rec: dict):
    authority=rec.get("authority_conflicts") or {}; deadline=authority.get("deadline") if isinstance(authority,dict) else {}; deadline=deadline if isinstance(deadline,dict) else {}; status=str(deadline.get("status") or "MISSING"); return deadline,status,status in RESOLVED_DEADLINE and not bool(deadline.get("conflict"))


def compact_review(rec: dict, run_id: str, shard: str, published_at: str) -> dict:
    evidence=rec.get("gate_evidence_candidates") or {}; coverage=sum(1 for items in evidence.values() if isinstance(items,list) and items); deadline,status,resolved=_deadline_info(rec)
    return {"candidate_id":rec.get("candidate_id"),"title":rec.get("title"),"buyer":rec.get("buyer"),"portal":rec.get("portal"),"notice_url":rec.get("notice_url"),"deadline":rec.get("deadline"),"estimated_value":rec.get("estimated_value"),"currency":rec.get("currency"),"preliminary_score":rec.get("preliminary_score"),"priority_score":int(rec.get("final_score") or 0),"content_quality":rec.get("content_quality"),"gate_readiness":bool(rec.get("gate_readiness")),"deadline_authority":deadline,"deadline_authority_status":status,"deadline_resolved":resolved,"evidence_gate_coverage":coverage,"evidence_by_gate":evidence,"source_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"source_shard":int(shard) if str(shard).isdigit() else shard,"hot_ready_at":published_at,"review_contract":"Gate-ready authoritative DCE evidence pack. ChatGPT must use only supplied evidence plus explicitly known bidder facts; missing bidder facts stay UNKNOWN. FINAL_SUPER_GREEN requires every mandatory gate resolved and authoritative deadline reconciliation."}


def _deadline_open(rec: dict) -> bool:
    try: return date.fromisoformat(str(rec.get("deadline") or "")[:10]) >= datetime.now(timezone.utc).date()
    except Exception: return True


def review_sort_key(rec: dict): return (bool(rec.get("deadline_resolved")),int(rec.get("priority_score") or 0),int(rec.get("evidence_gate_coverage") or 0),str(rec.get("hot_ready_at") or ""))


def merge_review(existing: dict, incoming: list[dict], resolved_keys: set[str], run_id: str, shard: str, max_items: int) -> dict:
    merged={}
    for rec in existing.get("items") or []:
        if isinstance(rec,dict) and item_key(rec) not in resolved_keys and _deadline_open(rec): merged[item_key(rec)]=rec
    for rec in incoming:
        if not _deadline_open(rec): continue
        k=item_key(rec); cur=merged.get(k)
        if cur is None or review_sort_key(rec)>=review_sort_key(cur): merged[k]=rec
    items=sorted(merged.values(),key=review_sort_key,reverse=True)[:max_items]
    return {"schema":"GPT_REVIEW_HOT_V1","updated_at":utc_now(),"latest_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"latest_shard":int(shard) if str(shard).isdigit() else shard,"count":len(items),"items":items,"instruction":"Review highest-ranked items first. These are DCE evidence packs, not final verdicts. Unknown is never PASS. Apply the Tender mandatory-gate contract and deadline authority before returning FINAL_SUPER_GREEN."}


def github_get(repo: str, path: str, branch: str, token: str):
    url=f"https://api.github.com/repos/{repo}/contents/{path}"; headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"tender-hot-publisher/2.0"}; r=requests.get(url,headers=headers,params={"ref":branch},timeout=30)
    if r.status_code==404: return {},None
    r.raise_for_status(); obj=r.json(); raw=base64.b64decode(obj.get("content") or b"").decode("utf-8",errors="replace")
    try: current=json.loads(raw) if raw.strip() else {}
    except Exception: current={}
    return current if isinstance(current,dict) else {},obj.get("sha")


def github_put(repo: str, path: str, branch: str, token: str, payload: dict, sha: str|None, message: str):
    url=f"https://api.github.com/repos/{repo}/contents/{path}"; headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"tender-hot-publisher/2.0"}; body={"message":message,"content":base64.b64encode((json.dumps(payload,indent=2,ensure_ascii=False)+"\n").encode()).decode(),"branch":branch}
    if sha: body["sha"]=sha
    return requests.put(url,headers=headers,json=body,timeout=45)


def publish_retry(repo,path,branch,token,builder,message,attempts):
    last=None
    for attempt in range(1,max(1,attempts)+1):
        try:
            existing,sha=github_get(repo,path,branch,token); payload=builder(existing); r=github_put(repo,path,branch,token,payload,sha,message)
            if r.status_code in {200,201}: return {"published":True,"attempt":attempt,"path":path,"payload":payload}
            last=f"GitHub PUT {r.status_code}: {r.text[:800]}"
            if r.status_code not in {409,422}: raise RuntimeError(last)
        except Exception as exc: last=str(exc)
        if attempt<attempts: time.sleep(min(8.0,0.35*attempt+random.random()*0.9))
    raise RuntimeError(f"publish failed for {path}: {last}")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--review",required=True); ap.add_argument("--run-id",required=True); ap.add_argument("--shard",required=True); ap.add_argument("--repo",default=os.getenv("GITHUB_REPOSITORY","")); ap.add_argument("--branch",default="main"); ap.add_argument("--path",default="control/supergreen_hot.json"); ap.add_argument("--review-path",default="control/gpt_review_hot.json"); ap.add_argument("--max-green",type=int,default=200); ap.add_argument("--max-review",type=int,default=30); ap.add_argument("--attempts",type=int,default=12); ap.add_argument("--out",default="supergreen_hot_candidate.json"); args=ap.parse_args()
    records=load_records(Path(args.review)); published_at=utc_now(); green_incoming=[compact_green(r,args.run_id,args.shard,published_at) for r in records if str(r.get("classification") or "").upper() in GREEN_CLASSES]; review_incoming=[compact_review(r,args.run_id,args.shard,published_at) for r in records if str(r.get("classification") or "").upper()==REVIEW_CLASS and r.get("gate_readiness") and r.get("gate_evidence_candidates")]; resolved_keys={item_key(r) for r in records if str(r.get("classification") or "").upper()!=REVIEW_CLASS}
    token=(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not args.repo or not token: raise SystemExit("GITHUB_REPOSITORY/GH_TOKEN required for hot publication")
    result={"schema":"TENDER_HOT_PUBLISH_V2","run_id":args.run_id,"shard":args.shard,"green_delta":len(green_incoming),"review_delta":len(review_incoming),"green":None,"gpt_review":None}
    if green_incoming: result["green"]=publish_retry(args.repo,args.path,args.branch,token,lambda e:merge_green(e,green_incoming,args.run_id,args.shard,args.max_green),f"tender: hot green DCE {args.run_id} shard {args.shard}",args.attempts)
    if review_incoming or resolved_keys: result["gpt_review"]=publish_retry(args.repo,args.review_path,args.branch,token,lambda e:merge_review(e,review_incoming,resolved_keys,args.run_id,args.shard,args.max_review),f"tender: GPT-ready DCE bank {args.run_id} shard {args.shard}",args.attempts)
    Path(args.out).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); print(json.dumps({"published":bool(result["green"] or result["gpt_review"]),"green_delta":len(green_incoming),"review_delta":len(review_incoming),"green_path":args.path if result["green"] else None,"gpt_review_path":args.review_path if result["gpt_review"] else None},ensure_ascii=False))


if __name__ == "__main__": main()
