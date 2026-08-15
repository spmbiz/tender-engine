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

GREEN_CLASSES={"FINAL_SUPER_GREEN","GREEN","GREEN_PARTNERABLE"}; REVIEW_CLASS="MODEL_REVIEW_REQUIRED"; CLASS_RANK={"FINAL_SUPER_GREEN":4,"GREEN":3,"GREEN_PARTNERABLE":2}; RESOLVED_DEADLINE={"CONSISTENT_NOTICE_DATE_FOUND_IN_DCE","DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING"}

def utc_now(): return datetime.now(timezone.utc).isoformat()

def load_records(path):
    text=Path(path).read_text(encoding="utf-8",errors="replace").strip()
    if not text:return []
    if Path(path).suffix.lower()==".jsonl":return [json.loads(x) for x in text.splitlines() if x.strip()]
    obj=json.loads(text)
    if isinstance(obj,list):return [x for x in obj if isinstance(x,dict)]
    if isinstance(obj,dict) and isinstance(obj.get("items"),list):return [x for x in obj["items"] if isinstance(x,dict)]
    return [obj] if isinstance(obj,dict) else []

def item_key(r):
    cid=str(r.get("candidate_id") or "").strip().casefold(); return cid or "|".join(str(r.get(k) or "").strip().casefold() for k in ("title","buyer","notice_url"))

def compact_green(r,run_id,shard,ts):
    gates=r.get("gates") or {}; statuses={str(n):str(i.get("status") or "UNKNOWN").upper() for n,i in gates.items() if isinstance(i,dict)}; resolved={"PASS","PASS_CONDITIONAL","NOT_APPLICABLE"}; cls=str(r.get("classification") or "").upper()
    return {"candidate_id":r.get("candidate_id"),"title":r.get("title"),"buyer":r.get("buyer"),"portal":r.get("portal"),"notice_url":r.get("notice_url"),"deadline":r.get("deadline"),"estimated_value":r.get("estimated_value"),"currency":r.get("currency"),"classification":cls,"final_score":int(r.get("final_score") or 0),"summary":r.get("summary"),"content_quality":r.get("content_quality"),"gate_readiness":bool(r.get("gate_readiness")),"gate_statuses":statuses,"unresolved_gates":[k for k,v in statuses.items() if v not in resolved],"hard_fail_gates":[k for k,v in statuses.items() if v=="FAIL_HARD"],"authority_conflicts":r.get("authority_conflicts") or {},"source_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"source_shard":int(shard) if str(shard).isdigit() else shard,"hot_published_at":ts}

def green_sort(r):return (CLASS_RANK.get(str(r.get("classification") or "").upper(),-1),int(r.get("final_score") or 0),str(r.get("hot_published_at") or ""))

def merge_green(existing,incoming,run_id,shard,max_green):
    merged={}
    for b in ("final_supergreens","greens"):
        for r in existing.get(b) or []:
            if isinstance(r,dict):merged[item_key(r)]=r
    for r in incoming:
        k=item_key(r); cur=merged.get(k)
        if cur is None or green_sort(r)>=green_sort(cur):merged[k]=r
    items=sorted(merged.values(),key=green_sort,reverse=True); finals=[x for x in items if x.get("classification")=="FINAL_SUPER_GREEN"][:max_green]; greens=[x for x in items if x.get("classification") in {"GREEN","GREEN_PARTNERABLE"}][:max_green]; runs=[]
    for v in [run_id]+list(existing.get("source_runs") or []):
        s=str(v).strip()
        if s and s not in runs:runs.append(s)
    return {"schema":"SUPERGREEN_HOT_V1","updated_at":utc_now(),"latest_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"latest_shard":int(shard) if str(shard).isdigit() else shard,"source_runs":runs[:20],"counts":{"final_supergreen":len(finals),"green_or_partnerable":len(greens)},"final_supergreens":finals,"greens":greens,"rule":"Hot green cache only. FINAL_SUPER_GREEN remains valid only when produced from authoritative DCE evidence and accepted by final_verdict_guard.py."}

def deadline_info(r):
    a=r.get("authority_conflicts") or {}; d=a.get("deadline") if isinstance(a,dict) else {}; d=d if isinstance(d,dict) else {}; s=str(d.get("status") or "MISSING"); return d,s,s in RESOLVED_DEADLINE and not bool(d.get("conflict"))

def compact_review(r,run_id,shard,ts):
    ev=r.get("gate_evidence_candidates") or {}; cov=sum(1 for x in ev.values() if isinstance(x,list) and x); d,s,res=deadline_info(r)
    return {"candidate_id":r.get("candidate_id"),"title":r.get("title"),"buyer":r.get("buyer"),"portal":r.get("portal"),"notice_url":r.get("notice_url"),"deadline":r.get("deadline"),"estimated_value":r.get("estimated_value"),"currency":r.get("currency"),"preliminary_score":r.get("preliminary_score"),"priority_score":int(r.get("final_score") or 0),"content_quality":r.get("content_quality"),"gate_readiness":bool(r.get("gate_readiness")),"deadline_authority":d,"deadline_authority_status":s,"deadline_resolved":res,"evidence_gate_coverage":cov,"evidence_by_gate":ev,"source_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"source_shard":int(shard) if str(shard).isdigit() else shard,"hot_ready_at":ts,"review_contract":"Gate-ready authoritative DCE evidence pack. Unknown is never PASS. FINAL_SUPER_GREEN requires every mandatory gate resolved and authoritative deadline reconciliation."}

def deadline_open(r):
    try:return date.fromisoformat(str(r.get("deadline") or "")[:10])>=datetime.now(timezone.utc).date()
    except Exception:return True

def review_sort(r):return (bool(r.get("deadline_resolved")),int(r.get("priority_score") or 0),int(r.get("evidence_gate_coverage") or 0),str(r.get("hot_ready_at") or ""))

def merge_review(existing,incoming,resolved_keys,run_id,shard,max_items):
    merged={}
    for r in existing.get("items") or []:
        if isinstance(r,dict) and item_key(r) not in resolved_keys and deadline_open(r):merged[item_key(r)]=r
    for r in incoming:
        if not deadline_open(r):continue
        k=item_key(r); cur=merged.get(k)
        if cur is None or review_sort(r)>=review_sort(cur):merged[k]=r
    items=sorted(merged.values(),key=review_sort,reverse=True)[:max_items]
    return {"schema":"GPT_REVIEW_HOT_V1","updated_at":utc_now(),"latest_dce_run_id":int(run_id) if str(run_id).isdigit() else run_id,"latest_shard":int(shard) if str(shard).isdigit() else shard,"count":len(items),"items":items,"instruction":"Review highest-ranked items first. These are DCE evidence packs, not final verdicts. Unknown is never PASS."}

def gh_get(repo,path,branch,token):
    url=f"https://api.github.com/repos/{repo}/contents/{path}"; h={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"tender-hot-publisher/2.0"}; r=requests.get(url,headers=h,params={"ref":branch},timeout=30)
    if r.status_code==404:return {},None
    r.raise_for_status(); o=r.json(); raw=base64.b64decode(o.get("content") or b"").decode("utf-8",errors="replace")
    try:cur=json.loads(raw) if raw.strip() else {}
    except Exception:cur={}
    return cur if isinstance(cur,dict) else {},o.get("sha")

def gh_put(repo,path,branch,token,payload,sha,msg):
    url=f"https://api.github.com/repos/{repo}/contents/{path}"; h={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"tender-hot-publisher/2.0"}; body={"message":msg,"content":base64.b64encode((json.dumps(payload,indent=2,ensure_ascii=False)+"\n").encode()).decode(),"branch":branch}
    if sha:body["sha"]=sha
    return requests.put(url,headers=h,json=body,timeout=45)

def publish(repo,path,branch,token,builder,msg,attempts):
    last=None
    for n in range(1,max(1,attempts)+1):
        try:
            cur,sha=gh_get(repo,path,branch,token); payload=builder(cur); r=gh_put(repo,path,branch,token,payload,sha,msg)
            if r.status_code in {200,201}:return {"published":True,"attempt":n,"path":path,"payload":payload}
            last=f"GitHub PUT {r.status_code}: {r.text[:800]}"
            if r.status_code not in {409,422}:raise RuntimeError(last)
        except Exception as e:last=str(e)
        if n<attempts:time.sleep(min(8.0,0.35*n+random.random()*0.9))
    raise RuntimeError(f"publish failed for {path}: {last}")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--review",required=True); ap.add_argument("--run-id",required=True); ap.add_argument("--shard",required=True); ap.add_argument("--repo",default=os.getenv("GITHUB_REPOSITORY","")); ap.add_argument("--branch",default="main"); ap.add_argument("--path",default="control/supergreen_hot.json"); ap.add_argument("--review-path",default="control/gpt_review_hot.json"); ap.add_argument("--max-green",type=int,default=200); ap.add_argument("--max-review",type=int,default=30); ap.add_argument("--attempts",type=int,default=12); ap.add_argument("--out",default="supergreen_hot_candidate.json"); a=ap.parse_args(); rows=load_records(a.review); ts=utc_now(); greens=[compact_green(r,a.run_id,a.shard,ts) for r in rows if str(r.get("classification") or "").upper() in GREEN_CLASSES]; reviews=[compact_review(r,a.run_id,a.shard,ts) for r in rows if str(r.get("classification") or "").upper()==REVIEW_CLASS and r.get("gate_readiness") and r.get("gate_evidence_candidates")]; resolved={item_key(r) for r in rows if str(r.get("classification") or "").upper()!=REVIEW_CLASS}; token=(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not a.repo or not token:raise SystemExit("GITHUB_REPOSITORY/GH_TOKEN required for hot publication")
    result={"green_delta":len(greens),"review_delta":len(reviews),"green":None,"gpt_review":None}
    if greens:result["green"]=publish(a.repo,a.path,a.branch,token,lambda e:merge_green(e,greens,a.run_id,a.shard,a.max_green),f"tender: hot green DCE {a.run_id} shard {a.shard}",a.attempts)
    if reviews or resolved:result["gpt_review"]=publish(a.repo,a.review_path,a.branch,token,lambda e:merge_review(e,reviews,resolved,a.run_id,a.shard,a.max_review),f"tender: GPT-ready DCE bank {a.run_id} shard {a.shard}",a.attempts)
    Path(a.out).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); print(json.dumps({"published":bool(result["green"] or result["gpt_review"]),"green_delta":len(greens),"review_delta":len(reviews),"gpt_review_path":a.review_path if result["gpt_review"] else None},ensure_ascii=False))

if __name__=="__main__":main()
