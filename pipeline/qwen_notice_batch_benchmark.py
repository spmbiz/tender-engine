#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

DECISIONS = {"STRONG_FIT", "FIT", "MAYBE", "REJECT_OBVIOUS"}
LEAN = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
ROUTES = {"DIRECT_DIGITAL", "AI_ENABLED", "SUBCONTRACTABLE", "BROKER_RESELL", "MIXED", "UNCLEAR"}
FRICTION = {
    "REGULATED_GOODS", "LICENSED_PERSONNEL", "HEAVY_EQUIPMENT", "CAPITAL_INTENSIVE",
    "ON_SITE_SPECIALIST", "LOCAL_PRESENCE", "MANUFACTURER_AUTHORIZATION",
    "FRAMEWORK_OR_REFERENCE_BURDEN", "SECURITY_CLEARANCE", "OTHER"
}
PROMPT_VERSION = "qwen-notice-batch-high-recall-lean-axis-v1"
CLASSIFIER_VERSION = "qwen3-4b-q4km-batch-shadow-v1"
SCHEMA = "QWEN_NOTICE_BATCH_SHADOW_V1"
SUMMARY_SCHEMA = "QWEN_NOTICE_BATCH_BENCHMARK_SUMMARY_V1"

SYSTEM = """You classify public procurement notices for a lean Belgian SME.
This is HIGH-RECALL ROUTING, not final eligibility or bid approval.
The SME can deliver digital/AI/software/content work directly and can also subcontract specialists or broker/resell ordinary goods/services.
Never confuse technically possible fulfillment with commercial attractiveness.
For each notice return TWO separate judgments:
1) decision = semantic survival: STRONG_FIT, FIT, MAYBE, REJECT_OBVIOUS. Reject only clearly implausible even through direct, AI, subcontract, consortium, ordinary brokerage/resale, or operations. Unknown/unusual survives as MAYBE.
2) lean_attractiveness = HIGH, MEDIUM, LOW, UNKNOWN. Heavy capex, regulated goods, licensed/local specialist labor, security clearances, specialized installation, or authorization burden usually lower lean attractiveness even if decision survives.
Do not invent DCE permissions, eligibility, references, licenses, deadlines, margins, supplier availability, or certifications.
Return ONLY a JSON array with exactly one compact object per supplied id and in the same order. /no_think"""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def opener(path: Path, mode: str):
    return gzip.open(path, mode + "t", encoding="utf-8") if path.suffix == ".gz" else path.open(mode, encoding="utf-8")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with opener(path, "r") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def notice(row: dict[str, Any]) -> dict[str, Any]:
    n = row.get("notice")
    return n if isinstance(n, dict) else row


def cid(row: dict[str, Any]) -> str:
    n = notice(row)
    return str(row.get("canonical_notice_id") or n.get("candidate_id") or n.get("notice_id") or n.get("id") or "").strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get("material_fields_hash") or row.get("input_material_fields_hash") or "").strip()


def deterministic_sample(rows: Iterable[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        candidate = cid(row)
        if not candidate:
            continue
        ranked.append((hashlib.sha256(candidate.encode()).hexdigest(), candidate, row))
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in ranked[:n]]


def compact(row: dict[str, Any], description_chars: int) -> dict[str, Any]:
    n = notice(row)
    desc = " ".join(str(n.get("description") or "").split())
    if len(desc) > description_chars:
        desc = desc[:description_chars] + " …"
    return {
        "id": cid(row),
        "source": n.get("source"),
        "country": n.get("country"),
        "buyer": n.get("buyer"),
        "title": n.get("title"),
        "description": desc,
        "cpv_or_category": n.get("cpv_or_category"),
        "estimated_value": n.get("estimated_value"),
        "currency": n.get("currency"),
        "deadline": n.get("deadline") or n.get("deadline_utc"),
        "procedure": n.get("procedure"),
        "lots": n.get("lots"),
        "notice_eligibility": n.get("notice_eligibility"),
        "subcontracting": n.get("subcontracting"),
    }


def prompt(batch: list[dict[str, Any]], description_chars: int) -> str:
    notices = [compact(x, description_chars) for x in batch]
    return """For every input id return:
{id, decision, confidence, lean_attractiveness, possible_delivery_route, friction_flags, unusual_or_novel, needs_gpt_review, reason}.
confidence is 0..1. friction_flags is an array using only: REGULATED_GOODS, LICENSED_PERSONNEL, HEAVY_EQUIPMENT, CAPITAL_INTENSIVE, ON_SITE_SPECIALIST, LOCAL_PRESENCE, MANUFACTURER_AUTHORIZATION, FRAMEWORK_OR_REFERENCE_BURDEN, SECURITY_CLEARANCE, OTHER.
reason max 14 words. Never omit an id. Keep same order. JSON array only. /no_think
NOTICES=""" + json.dumps(notices, ensure_ascii=False, separators=(",", ":"))


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def extract_array(text: str) -> list[dict[str, Any]] | None:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except Exception:
        pass
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return [x for x in obj if isinstance(x, dict)] if isinstance(obj, list) else None
    except Exception:
        return None


def normalize(obj: dict[str, Any] | None, expected_id: str, parse_error: str | None) -> dict[str, Any]:
    if not obj:
        return {
            "decision": "MAYBE", "confidence": 0.0, "lean_attractiveness": "UNKNOWN",
            "possible_delivery_route": "UNCLEAR", "friction_flags": [], "unusual_or_novel": True,
            "needs_gpt_review": True, "reason": "Batch output missing; high-recall fallback retained notice.",
            "parse_error": parse_error or "missing_batch_item"
        }
    decision = str(obj.get("decision") or "MAYBE").upper()
    if decision not in DECISIONS:
        decision = "MAYBE"; parse_error = parse_error or "invalid_decision"
    lean = str(obj.get("lean_attractiveness") or "UNKNOWN").upper()
    if lean not in LEAN:
        lean = "UNKNOWN"; parse_error = parse_error or "invalid_lean"
    route = str(obj.get("possible_delivery_route") or "UNCLEAR").upper()
    if route not in ROUTES:
        route = "UNCLEAR"; parse_error = parse_error or "invalid_route"
    flags = obj.get("friction_flags") if isinstance(obj.get("friction_flags"), list) else []
    flags = [str(x).upper() for x in flags if str(x).upper() in FRICTION]
    try:
        confidence = min(1.0, max(0.0, float(obj.get("confidence", 0))))
    except Exception:
        confidence = 0.0
    return {
        "decision": decision,
        "confidence": confidence,
        "lean_attractiveness": lean,
        "possible_delivery_route": route,
        "friction_flags": flags,
        "unusual_or_novel": bool(obj.get("unusual_or_novel", False)),
        "needs_gpt_review": bool(obj.get("needs_gpt_review", False)),
        "reason": " ".join(str(obj.get("reason") or "").split())[:300],
        "parse_error": parse_error,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--batch-size", type=int, required=True)
    ap.add_argument("--sample-size", type=int, default=32)
    ap.add_argument("--server", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--description-chars", type=int, default=900)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--startup-seconds", type=float, default=0.0)
    ap.add_argument("--source-ledger-generation", required=True)
    args = ap.parse_args()
    if args.batch_size < 1 or args.batch_size > 32:
        raise SystemExit("batch-size must be 1..32")

    sample = deterministic_sample(iter_jsonl(Path(args.queue)), args.sample_size)
    out_path = Path(args.out); summary_path = Path(args.summary)
    out_path.write_text("", encoding="utf-8")
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    batch_failures = 0
    request_count = 0

    with out_path.open("a", encoding="utf-8") as fh:
        for start in range(0, len(sample), args.batch_size):
            batch = sample[start:start + args.batch_size]
            request_count += 1
            text = ""; usage = {}; arr = None; batch_error = None
            t0 = time.monotonic()
            try:
                response = post_json(args.server, {
                    "model": args.model,
                    "messages": [{"role":"system","content":SYSTEM},{"role":"user","content":prompt(batch,args.description_chars)}],
                    "temperature": 0.1, "top_p": 0.8, "max_tokens": args.max_tokens, "stream": False,
                }, args.timeout)
                text = str(response["choices"][0]["message"]["content"])
                usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
                arr = extract_array(text)
                if arr is None:
                    batch_error = "invalid_json_array"
            except Exception as exc:
                batch_error = f"request_error:{type(exc).__name__}"
            if batch_error:
                batch_failures += 1
            by_id = {str(x.get("id") or "").strip(): x for x in (arr or []) if str(x.get("id") or "").strip()}
            latency = round(time.monotonic() - t0, 3)
            for row in batch:
                candidate = cid(row)
                obj = by_id.get(candidate)
                per_error = batch_error or (None if obj is not None else "missing_id_in_batch_output")
                norm = normalize(obj, candidate, per_error)
                record = {
                    "schema": SCHEMA,
                    "canonical_notice_id": candidate,
                    "input_material_fields_hash": material_hash(row),
                    "source_ledger_generation": args.source_ledger_generation,
                    "classifier_model": args.model,
                    "classifier_quant": "Q4_K_M",
                    "classifier_prompt_version": PROMPT_VERSION,
                    "classifier_version": CLASSIFIER_VERSION,
                    "batch_size": args.batch_size,
                    "batch_request_index": request_count,
                    "batch_latency_seconds": latency,
                    "usage": usage,
                    "classified_at_utc": now_utc(),
                    **norm,
                    "notice": compact(row, args.description_chars),
                }
                results.append(record)
                fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()

    elapsed = time.monotonic() - started
    ids = [x["canonical_notice_id"] for x in results]
    decision_counts = Counter(x["decision"] for x in results)
    lean_counts = Counter(x["lean_attractiveness"] for x in results)
    parse_errors = sum(1 for x in results if x.get("parse_error"))
    summary = {
        "schema": SUMMARY_SCHEMA,
        "classifier_model": args.model,
        "classifier_prompt_version": PROMPT_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "source_ledger_generation": args.source_ledger_generation,
        "sample_requested": args.sample_size,
        "sample_completed": len(results),
        "unique_ids": len(set(ids)),
        "batch_size": args.batch_size,
        "request_count": request_count,
        "batch_failures": batch_failures,
        "parse_or_missing_item_errors": parse_errors,
        "startup_seconds": args.startup_seconds,
        "inference_seconds": round(elapsed, 3),
        "seconds_per_notice": round(elapsed / len(results), 3) if results else None,
        "notices_per_second": round(len(results) / elapsed, 4) if elapsed and results else None,
        "decision_counts": dict(sorted(decision_counts.items())),
        "lean_attractiveness_counts": dict(sorted(lean_counts.items())),
        "row_conservation_pass": len(results) == len(sample) == len(set(ids)),
        "data_safety": {
            "shadow_only": True,
            "drops_or_deletes_notices": False,
            "automatic_rejection_enabled": False,
            "batch_failure_fallback": "MAYBE+UNKNOWN+needs_gpt_review"
        },
        "updated_at_utc": now_utc(),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not summary["row_conservation_pass"]:
        raise SystemExit("row conservation failed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
