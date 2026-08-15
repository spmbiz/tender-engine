from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from authority_conflicts import process as reconcile_authority
from final_verdict_guard import REQUIRED_GATES, validate_record

ALLOWED_GATE_STATUSES = {"PASS", "PASS_CONDITIONAL", "FAIL_HARD", "UNKNOWN", "NOT_APPLICABLE"}
FINAL_CLASSIFICATIONS = {"FINAL_SUPER_GREEN"}
MODEL_CLASSIFICATIONS = {"FINAL_SUPER_GREEN", "GREEN", "GREEN_PARTNERABLE", "YELLOW", "RED", "MODEL_REVIEW_REQUIRED"}
RETRYABLE_HTTP = {408, 409, 429, 500, 502, 503, 504}

SYSTEM_PROMPT = """You are adjudicating public procurement opportunities for a very small Belgian supplier.
Use ONLY the authoritative DCE evidence supplied in the JSON input. Never infer a PASS from missing text.
Never invent bidder turnover, references, staff, certifications, insurance, local presence, language skills, equipment, or past performance.
For every mandatory gate return one of PASS, PASS_CONDITIONAL, FAIL_HARD, UNKNOWN, NOT_APPLICABLE.
PASS/PASS_CONDITIONAL must cite one or more supplied evidence_refs for that exact gate.
If a requirement exists but the bidder's compliance is not proven by supplied facts, use UNKNOWN, unless the DCE explicitly permits reliance/consortium and the correct result is GREEN_PARTNERABLE.
A FINAL_SUPER_GREEN / score >=90 is allowed only when all mandatory gates are resolved from authoritative DCE evidence and the submission deadline is authoritatively reconciled with no conflict.
Return strict JSON only. No markdown."""


def load_jsonl(path: Path):
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj


def number_evidence(row: dict):
    refs = {}; gates = {}; snippets = row.get("gate_snippets") or {}
    for gate in REQUIRED_GATES:
        numbered = []
        for i, item in enumerate((snippets.get(gate) or [])[:12], 1):
            ref = f"{gate}:{i}"
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("snippet") or item.get("evidence") or item)
                source = item.get("source") or item.get("file") or item.get("path")
            else:
                text = str(item); source = None
            refs[ref] = {"ref": ref, "text": text[:5000], "source": source}
            numbered.append({"ref": ref, "text": text[:2400], "source": source})
        gates[gate] = numbered
    return refs, gates


def compact_review_evidence(row: dict, per_gate: int = 3, chars: int = 1400) -> dict:
    snippets = row.get("gate_snippets") or {}; packed: dict[str, list[dict]] = {}
    for gate in REQUIRED_GATES:
        out = []
        for item in list(snippets.get(gate) or [])[:per_gate]:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("snippet") or item.get("evidence") or "")
                source = item.get("source") or item.get("file") or item.get("path")
            else:
                text = str(item or ""); source = None
            text = " ".join(text.split())[:chars]
            if text:
                out.append({"text": text, "source": source})
        packed[gate] = out
    return packed


def refresh_authority(row: dict) -> dict:
    if not row.get("gate_readiness"):
        return row
    rel = str(row.get("artifact_relative_root") or "").strip()
    if not rel:
        return row
    base = Path(os.getenv("DCE_FAST_ROOT", "out")) / rel
    if not (base / "manifest.json").exists():
        return row
    try:
        authority = reconcile_authority(base)
    except Exception as exc:
        row["authority_refresh_error"] = str(exc)[:500]; return row
    row["authority_conflicts"] = authority
    deadline = authority.get("deadline") if isinstance(authority, dict) else None
    if isinstance(deadline, dict):
        row["deadline_authority_status"] = deadline.get("status")
        row["deadline_conflict"] = bool(deadline.get("conflict"))
    return row


def output_text(response: dict) -> str:
    for item in response.get("output") or []:
        if isinstance(item, dict):
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
    return ""


def call_model(row: dict, model: str, api_key: str, retries: int = 2):
    refs, gates = number_evidence(row)
    payload = {
        "candidate": {k: row.get(k) for k in ("candidate_id","title","buyer","portal","deadline","estimated_value","currency","notice_url","content_quality","gate_readiness")},
        "authority_conflicts": row.get("authority_conflicts"),
        "mandatory_gates": REQUIRED_GATES,
        "evidence_refs_by_gate": gates,
        "required_output": {"classification":"one of FINAL_SUPER_GREEN/GREEN/GREEN_PARTNERABLE/YELLOW/RED/MODEL_REVIEW_REQUIRED","score":"integer 0..100","summary":"short operational verdict","gates":{gate:{"status":"...","evidence_refs":[],"notes":"..."} for gate in REQUIRED_GATES}},
    }
    body = {"model": model,"input":[{"role":"system","content":[{"type":"input_text","text":SYSTEM_PROMPT}]},{"role":"user","content":[{"type":"input_text","text":json.dumps(payload, ensure_ascii=False)}]}],"text":{"format":{"type":"json_object"}},"max_output_tokens":5000,"store":False}
    last_error = None
    for attempt in range(1, max(0, retries) + 2):
        try:
            r = requests.post("https://api.openai.com/v1/responses", headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}, json=body, timeout=180)
            if r.status_code >= 400:
                last_error = RuntimeError(f"OpenAI {r.status_code}: {r.text[:800]}")
                if r.status_code not in RETRYABLE_HTTP or attempt > retries:
                    raise last_error
            else:
                text = output_text(r.json()).strip()
                if not text:
                    raise RuntimeError("OpenAI response contained no output_text")
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
                obj = json.loads(text)
                if not isinstance(obj, dict):
                    raise RuntimeError("model output was not a JSON object")
                return obj, refs
        except (requests.RequestException, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt > retries:
                raise
        try:
            retry_after = float(r.headers.get("retry-after") or 0) if 'r' in locals() else 0
        except Exception:
            retry_after = 0
        time.sleep(max(retry_after or 0, min(8.0, 0.7 * attempt + random.random())))
    raise RuntimeError(str(last_error or "model call failed"))


def fallback_record(row: dict, reason: str, model: str | None = None):
    try: prelim = min(89, int(float(row.get("preliminary_score") or 0)))
    except Exception: prelim = 0
    return {
        "candidate_id":row.get("candidate_id"),"title":row.get("title"),"buyer":row.get("buyer"),"portal":row.get("portal"),"notice_url":row.get("notice_url"),"deadline":row.get("deadline"),"estimated_value":row.get("estimated_value"),"currency":row.get("currency"),"preliminary_score":row.get("preliminary_score"),
        "classification":"MODEL_REVIEW_REQUIRED","final_score":prelim,"summary":reason,"model":model,"model_review_completed":False,"content_quality":row.get("content_quality"),"gate_readiness":bool(row.get("gate_readiness")),"evidence_quality":row.get("evidence_quality") or {},"authority_conflicts":row.get("authority_conflicts") or {},"gate_evidence_candidates":compact_review_evidence(row),
        "gates":{gate:{"status":"UNKNOWN","evidence":[],"notes":"Awaiting model/manual adjudication; absence of evidence is not a PASS."} for gate in REQUIRED_GATES},
    }


def normalize_model_record(row: dict, obj: dict, refs: dict, model: str):
    classification = str(obj.get("classification") or "MODEL_REVIEW_REQUIRED").upper()
    if classification not in MODEL_CLASSIFICATIONS: classification = "MODEL_REVIEW_REQUIRED"
    try: score = max(0, min(100, int(float(obj.get("score") or 0))))
    except Exception: score = 0
    raw_gates = obj.get("gates") or {}; gates = {}
    for gate in REQUIRED_GATES:
        item = raw_gates.get(gate) if isinstance(raw_gates, dict) else None; item = item if isinstance(item, dict) else {}
        status = str(item.get("status") or "UNKNOWN").upper()
        if status not in ALLOWED_GATE_STATUSES: status = "UNKNOWN"
        requested_refs = item.get("evidence_refs") or []; requested_refs = requested_refs if isinstance(requested_refs, list) else []
        valid = [refs[x] for x in requested_refs if isinstance(x, str) and x in refs and x.startswith(gate + ":")]
        notes = str(item.get("notes") or "")[:3000]
        if status in {"PASS","PASS_CONDITIONAL"} and not valid:
            status = "UNKNOWN"; notes = (notes + " | Downgraded: no valid evidence ref supplied.").strip(" |").strip()
        if status == "NOT_APPLICABLE" and not notes:
            status = "UNKNOWN"; notes = "Downgraded: NOT_APPLICABLE lacked a reason."
        gates[gate] = {"status":status,"evidence":valid,"notes":notes}
    rec = {"candidate_id":row.get("candidate_id"),"title":row.get("title"),"buyer":row.get("buyer"),"portal":row.get("portal"),"notice_url":row.get("notice_url"),"deadline":row.get("deadline"),"estimated_value":row.get("estimated_value"),"currency":row.get("currency"),"preliminary_score":row.get("preliminary_score"),"classification":classification,"final_score":score,"summary":str(obj.get("summary") or "")[:5000],"model":model,"model_review_completed":True,"content_quality":row.get("content_quality"),"gate_readiness":bool(row.get("gate_readiness")),"evidence_quality":row.get("evidence_quality") or {},"authority_conflicts":row.get("authority_conflicts") or {},"gates":gates}
    violations = validate_record(rec)
    if violations:
        rec["guard_violations"] = violations
        if rec["classification"] in FINAL_CLASSIFICATIONS or rec["final_score"] >= 90:
            rec["classification"] = "MODEL_REVIEW_REQUIRED"; rec["final_score"] = min(89, rec["final_score"]); rec["gate_evidence_candidates"] = compact_review_evidence(row); rec["summary"] = (rec["summary"] + " | Finalization blocked by deterministic guard.").strip()
    return rec


def adjudicate_one(index: int, row: dict, model: str, api_key: str, retries: int):
    try:
        obj, refs = call_model(row, model, api_key, retries=retries); return index, normalize_model_record(row, obj, refs, model), False
    except Exception as exc:
        return index, fallback_record(row, f"Model adjudication error: {str(exc)[:700]}", model), True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--queue", required=True); ap.add_argument("--out", required=True); ap.add_argument("--max-model-reviews", type=int, default=80); ap.add_argument("--model-concurrency", type=int, default=int(os.getenv("OPENAI_ADJUDICATION_CONCURRENCY", "4"))); ap.add_argument("--model-retries", type=int, default=int(os.getenv("OPENAI_ADJUDICATION_RETRIES", "2"))); args = ap.parse_args()
    rows = [refresh_authority(r) for r in load_jsonl(Path(args.queue))]
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    api_key = os.getenv("OPENAI_API_KEY", "").strip(); model = os.getenv("OPENAI_ADJUDICATION_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    records: list[dict | None] = [None] * len(rows); review_jobs: list[tuple[int, dict]] = []; gate_ready_rows = [r for r in rows if r.get("gate_readiness")]; review_budget = max(0, args.max_model_reviews)
    for idx, row in enumerate(rows):
        if not row.get("gate_readiness"):
            rec = fallback_record(row, "Not gate-ready: authoritative DCE evidence is incomplete or unverified."); rec["classification"] = "YELLOW"; records[idx] = rec; continue
        if not api_key:
            records[idx] = fallback_record(row, "OPENAI_API_KEY unavailable: published to ChatGPT-ready hot review bank.", model); continue
        if len(review_jobs) >= review_budget:
            records[idx] = fallback_record(row, "Per-run model review cap reached; published to ChatGPT-ready hot review bank.", model); continue
        review_jobs.append((idx, row))
    model_errors = 0; workers = max(1, min(max(1, args.model_concurrency), len(review_jobs) or 1))
    if review_jobs:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(adjudicate_one, idx, row, model, api_key, max(0, args.model_retries)): idx for idx, row in review_jobs}
            for fut in as_completed(futures):
                idx, rec, errored = fut.result(); records[idx] = rec; model_errors += int(errored)
    final_records = [r for r in records if isinstance(r, dict)]
    with (out / "adjudication.jsonl").open("w", encoding="utf-8") as f:
        for rec in final_records: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    counts = Counter(str(r.get("classification") or "UNKNOWN") for r in final_records); finals = [r for r in final_records if r.get("classification") == "FINAL_SUPER_GREEN"]; greens = [r for r in final_records if r.get("classification") in {"FINAL_SUPER_GREEN","GREEN","GREEN_PARTNERABLE"}]; review_required = [r for r in final_records if r.get("classification") == "MODEL_REVIEW_REQUIRED"]; review_required.sort(key=lambda r: int(r.get("final_score") or 0), reverse=True)
    (out / "supergreen_shortlist.json").write_text(json.dumps({"dce_candidates":len(rows),"gate_ready":len(gate_ready_rows),"final_supergreen":len(finals),"green_or_partnerable":len(greens),"items":greens}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "review_required.json").write_text(json.dumps(review_required[:120], indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {"candidates":len(rows),"gate_ready":len(gate_ready_rows),"model_available":bool(api_key),"model":model if api_key else None,"model_attempts":len(review_jobs),"model_errors":model_errors,"model_concurrency":workers if review_jobs else 0,"classification_counts":dict(counts),"final_supergreen":len(finals),"green_or_partnerable":len(greens),"review_required":len(review_required),"chatgpt_hot_review_ready":sum(1 for r in review_required if r.get("gate_readiness") and r.get("gate_evidence_candidates")),"guard_contract":"FINAL_SUPER_GREEN/90+ is accepted only after final_verdict_guard.py returns no violations."}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"); print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
