from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SYSTEM = r'''You are the post-DCE pre-reader for SPM Business, a lean Belgian SME.
You receive ONLY evidence extracted from authoritative public procurement documents.
You are NOT the final adjudicator. Never output FINAL_SUPER_GREEN, GREEN, PASS, or claim bidder eligibility.
Goal: tell GPT Web which DCEs deserve immediate final review.
Use UNKNOWN when a decisive fact is absent. Never invent SPM turnover, references, staff, certifications, insurance, licences, citizenship, local establishment, or reseller status.
Classify commercial fit from the DCE evidence:
H = HOT: native lean SPM scope and no explicit blocker found; immediate GPT final review.
G = GOOD: attractive/plausible but material gates or delivery details still need GPT judgment.
M = MAYBE: partner-heavy, operationally heavy, economics unclear, or too many unknowns.
B = BLOCKED: explicit hard blocker/incompatibility appears in evidence.
U = INSUFFICIENT: evidence is not enough for meaningful business pre-read.
Lean l=H|M|L|U. Route r=D direct-digital, A AI-enabled, S subcontractable, B broker/resell, X mixed, U unclear.
Blocker codes b may only be used when explicit evidence supports them: GEO, TURNOVER, REF, CERT, STAFF, INSURANCE, SUBCONTRACT, ONSITE, SECURITY, RESELLER, SUBMISSION, IPDATA, DEADLINE, OTHER.
Critical unknown codes u can use the same gate concepts when evidence is missing/unclear.
g=1 only when GPT Web should review now.
p is a concise reason <=180 chars grounded in evidence.
Return ONLY {"x":[{"i":"id","d":"H|G|M|B|U","l":"H|M|L|U","r":"D|A|S|B|X|U","b":[],"u":[],"g":0,"p":"..."}, ...]} in exact input order. /no_think'''

D_MAP = {"H":"QWEN_DCE_HOT","G":"QWEN_DCE_GOOD","M":"QWEN_DCE_MAYBE","B":"QWEN_DCE_BLOCKED","U":"QWEN_DCE_INSUFFICIENT"}
L_MAP = {"H":"HIGH","M":"MEDIUM","L":"LOW","U":"UNKNOWN"}
R_MAP = {"D":"DIRECT_DIGITAL","A":"AI_ENABLED","S":"SUBCONTRACTABLE","B":"BROKER_RESELL","X":"MIXED","U":"UNCLEAR"}
ALLOWED_BLOCKERS = {"GEO","TURNOVER","REF","CERT","STAFF","INSURANCE","SUBCONTRACT","ONSITE","SECURITY","RESELLER","SUBMISSION","IPDATA","DEADLINE","OTHER"}
HARD_TEXT = (
    (re.compile(r"\b(?:u\.s\.? citizens? only|must be (?:a )?u\.s\.? citizen|united states citizen)\b", re.I), "GEO"),
    (re.compile(r"\b(?:top secret|secret clearance|security clearance|sci eligible)\b", re.I), "SECURITY"),
    (re.compile(r"\b(?:100% total small business set[- ]aside|small business set[- ]aside)\b", re.I), "GEO"),
    (re.compile(r"\b(?:manufacturer authori[sz]ation|required authorised reseller|required authorized reseller|sole authorised reseller|sole authorized reseller)\b", re.I), "RESELLER"),
)
GATES = (
    "entity_geography","turnover_financial","references_experience","certifications_partner","staffing_team",
    "insurance_bonds","subcontracting_consortium","deliverables_scope","sla_onsite","term_value","award_criteria",
    "forms_signatures","submission","ip_data_security","payment_tax",
)


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj


def nested_candidate(row: dict[str, Any]) -> dict[str, Any]:
    c=row.get("candidate")
    return c if isinstance(c,dict) else {}


def first(row: dict[str,Any], *names: str):
    c=nested_candidate(row)
    for src in (row,c):
        for name in names:
            val=src.get(name)
            if val not in (None,"",[],{}): return val
    return None


def evidence_map(row: dict[str,Any]) -> dict[str,Any]:
    for key in ("evidence_by_gate","gate_evidence_candidates"):
        v=row.get(key)
        if isinstance(v,dict): return v
    gs=row.get("gate_snippets")
    if isinstance(gs,dict):
        for key in ("gate_evidence","evidence_by_gate","categories"):
            v=gs.get(key)
            if isinstance(v,dict): return v
    return {}


def normalize_items(items: Any, per_gate: int, chars: int) -> list[str]:
    out=[]
    if not isinstance(items,list): return out
    for item in items[:per_gate]:
        if isinstance(item,dict): text=str(item.get("text") or item.get("snippet") or item.get("evidence") or "")
        else: text=str(item or "")
        text=" ".join(text.split())[:chars]
        if text: out.append(text)
    return out


def pack_row(row: dict[str,Any], per_gate: int, chars: int) -> tuple[dict[str,Any],dict[str,list[str]]]:
    ev=evidence_map(row)
    packed={g:normalize_items(ev.get(g),per_gate,chars) for g in GATES}
    return ({
        "i": str(first(row,"candidate_id") or ""),
        "t": first(row,"title"),
        "b": first(row,"buyer","contracting_authority"),
        "e": first(row,"deadline"),
        "v": first(row,"estimated_value","value"),
        "y": first(row,"currency"),
        "q": first(row,"content_quality"),
        "a": first(row,"deadline_authority_status"),
        "g": {k:v for k,v in packed.items() if v},
    }, packed)


def post(url: str, model: str, batch: list[dict[str,Any]], timeout: int, max_tokens: int) -> str:
    payload={
        "model":model,
        "messages":[{"role":"system","content":SYSTEM},{"role":"user","content":"Pre-read every DCE row in order:\n"+json.dumps(batch,ensure_ascii=False,separators=(",",":"))}],
        "temperature":0.0,
        "max_tokens":max_tokens,
    }
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        obj=json.loads(resp.read().decode())
    return str(obj["choices"][0]["message"]["content"])


def extract(text: str) -> list[dict[str,Any]]:
    text=text.strip(); candidates=[text]
    m=re.search(r"\{.*\}",text,re.S)
    if m and m.group(0)!=text: candidates.append(m.group(0))
    for c in candidates:
        try: obj=json.loads(c)
        except Exception: continue
        if isinstance(obj,dict) and isinstance(obj.get("x"),list): return [x for x in obj["x"] if isinstance(x,dict)]
    return []


def parse_deadline(value: Any):
    if not value: return None
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d
    except Exception: return None


def result_for(row: dict[str,Any], packed_evidence: dict[str,list[str]], model_item: dict[str,Any] | None, source_run: str) -> dict[str,Any]:
    cid=str(first(row,"candidate_id") or "")
    dcode=str((model_item or {}).get("d") or "U").upper()
    lcode=str((model_item or {}).get("l") or "U").upper()
    rcode=str((model_item or {}).get("r") or "U").upper()
    cls=D_MAP.get(dcode,"QWEN_DCE_INSUFFICIENT")
    blockers=[]
    for x in ((model_item or {}).get("b") or []):
        x=str(x).upper()
        if x in ALLOWED_BLOCKERS and x not in blockers: blockers.append(x)
    unknowns=[]
    for x in ((model_item or {}).get("u") or []):
        x=str(x).upper()
        if x in ALLOWED_BLOCKERS and x not in unknowns: unknowns.append(x)
    all_text=" ".join(t for arr in packed_evidence.values() for t in arr)
    for rx,code in HARD_TEXT:
        if rx.search(all_text) and code not in blockers: blockers.append(code)
    deadline=first(row,"deadline")
    parsed=parse_deadline(deadline)
    expired=bool(parsed and parsed < datetime.now(timezone.utc))
    if expired:
        cls="QWEN_DCE_BLOCKED"
        if "DEADLINE" not in blockers: blockers.append("DEADLINE")
    gate_ready=bool(row.get("gate_readiness"))
    if not gate_ready:
        cls="QWEN_DCE_INSUFFICIENT"
    hard=bool(set(blockers)&{"GEO","SECURITY","RESELLER","DEADLINE"})
    wants=bool((model_item or {}).get("g"))
    if expired: action="DROP_EXPIRED"
    elif not gate_ready: action="NEED_MORE_DCE"
    elif cls in {"QWEN_DCE_HOT","QWEN_DCE_GOOD"} and not hard and wants: action="FINAL_REVIEW_NOW"
    elif cls in {"QWEN_DCE_HOT","QWEN_DCE_GOOD","QWEN_DCE_MAYBE"} and not hard: action="REVIEW_IF_CAPACITY"
    elif hard or cls=="QWEN_DCE_BLOCKED": action="DROP_OR_PARTNER"
    else: action="NEED_MORE_DCE"
    base={"QWEN_DCE_HOT":86,"QWEN_DCE_GOOD":74,"QWEN_DCE_MAYBE":52,"QWEN_DCE_BLOCKED":12,"QWEN_DCE_INSUFFICIENT":28}[cls]
    if L_MAP.get(lcode)=="HIGH": base+=3
    if action=="FINAL_REVIEW_NOW": base+=2
    if unknowns: base-=min(12,2*len(unknowns))
    if blockers: base-=min(20,4*len(blockers))
    priority=max(0,min(89,base))
    return {
        "candidate_id":cid,"title":first(row,"title"),"buyer":first(row,"buyer","contracting_authority"),
        "portal":first(row,"portal"),"notice_url":first(row,"notice_url","source_url","url"),"deadline":deadline,
        "estimated_value":first(row,"estimated_value","value"),"currency":first(row,"currency"),
        "gate_readiness":gate_ready,"content_quality":first(row,"content_quality"),
        "deadline_authority_status":first(row,"deadline_authority_status"),
        "qwen_dce_classification":cls,"qwen_dce_lean":L_MAP.get(lcode,"UNKNOWN"),"qwen_dce_route":R_MAP.get(rcode,"UNCLEAR"),
        "explicit_blockers":blockers,"critical_unknowns":unknowns,"qwen_reason":str((model_item or {}).get("p") or "")[:220],
        "recommended_gpt_action":action,"gpt_priority_score":priority,"evidence_by_gate":packed_evidence,
        "source_dce_run_id":int(source_run) if str(source_run).isdigit() else source_run,
        "qwen_dce_version":"qwen3-4b-dce-gate-triage-v1",
        "finality":"PRE_READ_ONLY_NOT_FINAL_VERDICT",
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--queue",required=True); ap.add_argument("--out",required=True)
    ap.add_argument("--source-run",required=True); ap.add_argument("--shard-index",type=int,default=0); ap.add_argument("--shard-count",type=int,default=1)
    ap.add_argument("--server",default="http://127.0.0.1:8080/v1/chat/completions"); ap.add_argument("--model",default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--batch-size",type=int,default=4); ap.add_argument("--timeout",type=int,default=90); ap.add_argument("--max-tokens",type=int,default=1200)
    ap.add_argument("--per-gate",type=int,default=3); ap.add_argument("--evidence-chars",type=int,default=700)
    args=ap.parse_args()
    rows=[]
    for row in iter_jsonl(Path(args.queue)):
        if not row.get("gate_readiness"): continue
        cid=str(first(row,"candidate_id") or "")
        if not cid: continue
        bucket=int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%max(1,args.shard_count)
        if bucket==args.shard_index: rows.append(row)
    out=[]
    for start in range(0,len(rows),max(1,args.batch_size)):
        chunk=rows[start:start+max(1,args.batch_size)]
        prompts=[]; packed=[]
        for row in chunk:
            p,e=pack_row(row,args.per_gate,args.evidence_chars); prompts.append(p); packed.append(e)
        model_items=[]
        try: model_items=extract(post(args.server,args.model,prompts,args.timeout,args.max_tokens))
        except Exception: model_items=[]
        by_id={str(x.get("i") or ""):x for x in model_items}
        for row,e in zip(chunk,packed): out.append(result_for(row,e,by_id.get(str(first(row,"candidate_id") or "")),args.source_run))
    p=Path(args.out); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",encoding="utf-8") as f:
        for r in out: f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    print(json.dumps({"source_run":args.source_run,"shard":args.shard_index,"shards":args.shard_count,"gate_ready_rows":len(rows),"written":len(out),"final_review_now":sum(r['recommended_gpt_action']=='FINAL_REVIEW_NOW' for r in out)},indent=2))

if __name__=="__main__": main()
