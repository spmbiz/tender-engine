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

ALLOWED = {"STRONG_FIT", "FIT", "MAYBE", "REJECT_OBVIOUS"}
DELIVERY_MODES = {"DIRECT_DIGITAL", "AI_ENABLED", "SUBCONTRACTABLE", "BROKER_RESELL", "MIXED", "UNCLEAR"}
PROMPT_VERSION = "qwen-notice-high-recall-v2-fast"
CLASSIFIER_VERSION = "qwen3-4b-q4km-shadow-v2-fast-checkpointed"
SCHEMA = "QWEN_NOTICE_SHADOW_CLASSIFICATION_V2"
SUMMARY_SCHEMA = "QWEN_NOTICE_SHADOW_SMOKE_SUMMARY_V2"

SYSTEM = """You are a HIGH-RECALL public-tender opportunity classifier for a lean Belgian SME.
The business may deliver directly, use AI/software automation, subcontract specialists, form a consortium, broker/resell goods or services, or combine these modes.
This is TRIAGE, not eligibility adjudication. Notice metadata cannot prove DCE gates.
Prefer false positives over false negatives. Ambiguous, unusual, niche, novel, subcontractable, brokerable, resellable, or information-poor notices must be MAYBE rather than REJECT_OBVIOUS.
REJECT_OBVIOUS is reserved for clearly unsuitable work with no plausible lean direct, AI-enabled, subcontracted, consortium, broker/resell, or operational path.
Never call anything GREEN or SUPERGREEN.
Return one compact JSON object only. /no_think"""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def candidate_id(row: dict[str, Any]) -> str:
    notice = row.get("notice") if isinstance(row.get("notice"), dict) else row
    return str(row.get("canonical_notice_id") or notice.get("candidate_id") or notice.get("notice_id") or notice.get("id") or "").strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get("material_fields_hash") or row.get("input_material_fields_hash") or "").strip()


def deterministic_sample(rows: Iterable[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        cid = candidate_id(row)
        if not cid:
            continue
        key = hashlib.sha256(cid.encode("utf-8")).hexdigest()
        ranked.append((key, cid, row))
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in ranked[: max(0, n)]]


def compact_notice(envelope: dict[str, Any], description_chars: int) -> dict[str, Any]:
    row = envelope.get("notice") if isinstance(envelope.get("notice"), dict) else envelope
    description = " ".join(str(row.get("description") or "").split())
    if len(description) > description_chars:
        description = description[:description_chars] + " …[truncated]"
    return {
        "candidate_id": candidate_id(envelope),
        "source": row.get("source"),
        "country": row.get("country"),
        "buyer": row.get("buyer"),
        "title": row.get("title"),
        "description": description,
        "cpv_or_category": row.get("cpv_or_category"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "deadline": row.get("deadline") or row.get("deadline_utc"),
        "procedure": row.get("procedure"),
        "lots": row.get("lots"),
        "notice_eligibility": row.get("notice_eligibility"),
        "subcontracting": row.get("subcontracting"),
    }


def user_prompt(row: dict[str, Any], description_chars: int) -> str:
    return """Classify exactly one: STRONG_FIT, FIT, MAYBE, REJECT_OBVIOUS.
High recall is mandatory. Digital/IT/software/data/design/video/content/printing/consulting/operational work and plausible broker/resell/subcontract paths must not be rejected just because delivery details are unknown.
JSON keys only: classification, confidence (0..1), novelty_or_unusual_flag (boolean), delivery_mode (DIRECT_DIGITAL|AI_ENABLED|SUBCONTRACTABLE|BROKER_RESELL|MIXED|UNCLEAR), reason (max 18 words).
/no_think
NOTICE:
""" + json.dumps(compact_notice(row, description_chars), ensure_ascii=False, separators=(",", ":"))


def classifier_input_hash(envelope: dict[str, Any], description_chars: int) -> str:
    payload = {
        "system": SYSTEM,
        "user": user_prompt(envelope, description_chars),
        "material_fields_hash": material_hash(envelope),
        "prompt_version": PROMPT_VERSION,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def normalize(raw: dict[str, Any] | None, parse_error: str | None = None) -> dict[str, Any]:
    if not raw:
        return {
            "classification": "MAYBE",
            "confidence": 0.0,
            "novelty_or_unusual_flag": True,
            "delivery_mode": "UNCLEAR",
            "reason": "Model unavailable or invalid; high-recall fallback retains notice.",
            "parse_error": parse_error or "invalid_json",
        }
    classification = str(raw.get("classification") or "MAYBE").upper()
    if classification not in ALLOWED:
        classification = "MAYBE"
        parse_error = parse_error or "invalid_classification"
    mode = str(raw.get("delivery_mode") or "UNCLEAR").upper()
    if mode not in DELIVERY_MODES:
        mode = "UNCLEAR"
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.0))))
    except Exception:
        confidence = 0.0
    reason = " ".join(str(raw.get("reason") or "").split())[:350]
    return {
        "classification": classification,
        "confidence": confidence,
        "novelty_or_unusual_flag": bool(raw.get("novelty_or_unusual_flag", False)),
        "delivery_mode": mode,
        "reason": reason,
        "parse_error": parse_error,
    }


def summary_payload(
    output: list[dict[str, Any]],
    sample_requested: int,
    startup_seconds: float,
    started: float,
    source_ledger_generation: str,
    stopped_early: bool,
) -> dict[str, Any]:
    elapsed = time.monotonic() - started
    counts = Counter(x["classification"] for x in output)
    parse_errors = sum(1 for x in output if x.get("parse_error"))
    return {
        "schema": SUMMARY_SCHEMA,
        "classifier_model": "Qwen/Qwen3-4B-GGUF:Q4_K_M",
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": PROMPT_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "source_ledger_generation": source_ledger_generation,
        "sample_requested": sample_requested,
        "sample_completed": len(output),
        "startup_seconds": round(startup_seconds, 3),
        "inference_seconds": round(elapsed, 3),
        "notices_per_second": round(len(output) / elapsed, 4) if elapsed and output else None,
        "seconds_per_notice": round(elapsed / len(output), 3) if output else None,
        "parse_errors": parse_errors,
        "classification_counts": dict(sorted(counts.items())),
        "stopped_early_for_runtime_budget": stopped_early,
        "data_safety": {
            "shadow_only": True,
            "drops_or_deletes_notices": False,
            "automatic_rejection_enabled": False,
            "checkpointed_after_each_notice": True,
            "unknown_or_parse_failure_becomes": "MAYBE",
        },
        "updated_at_utc": now_utc(),
    }


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--server", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--sample-size", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=75)
    ap.add_argument("--startup-seconds", type=float, default=0.0)
    ap.add_argument("--description-chars", type=int, default=1800)
    ap.add_argument("--max-tokens", type=int, default=100)
    ap.add_argument("--max-runtime-seconds", type=int, default=900)
    ap.add_argument("--source-ledger-generation", default="UNKNOWN")
    args = ap.parse_args()

    sample = deterministic_sample(iter_jsonl(Path(args.queue)), args.sample_size)
    output: list[dict[str, Any]] = []
    started = time.monotonic()
    out_path = Path(args.out)
    summary_path = Path(args.summary)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("", encoding="utf-8")

    stopped_early = False
    with out_path.open("a", encoding="utf-8") as out_fh:
        for envelope in sample:
            # Exit cleanly before the Actions job timeout. Completed rows already exist on disk.
            if output and (time.monotonic() - started) >= args.max_runtime_seconds:
                stopped_early = True
                break

            cid = candidate_id(envelope)
            t0 = time.monotonic()
            parse_error = None
            raw_obj = None
            raw_text = ""
            usage: dict[str, Any] = {}
            try:
                response = post_json(
                    args.server,
                    {
                        "model": args.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user_prompt(envelope, args.description_chars)},
                        ],
                        "temperature": 0.1,
                        "top_p": 0.8,
                        "max_tokens": args.max_tokens,
                        "stream": False,
                    },
                    args.timeout,
                )
                raw_text = str(response["choices"][0]["message"]["content"])
                raw_obj = extract_object(raw_text)
                usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
                if raw_obj is None:
                    parse_error = "invalid_json"
            except Exception as exc:
                parse_error = f"request_error:{type(exc).__name__}"

            result = normalize(raw_obj, parse_error)
            result.update(
                {
                    "schema": SCHEMA,
                    "canonical_notice_id": cid,
                    "input_material_fields_hash": material_hash(envelope),
                    "classifier_input_hash": classifier_input_hash(envelope, args.description_chars),
                    "source_ledger_generation": args.source_ledger_generation,
                    "classifier_model": args.model,
                    "classifier_quant": "Q4_K_M",
                    "classifier_prompt_version": PROMPT_VERSION,
                    "classifier_version": CLASSIFIER_VERSION,
                    "classified_at_utc": now_utc(),
                    "latency_seconds": round(time.monotonic() - t0, 3),
                    "usage": usage,
                    "notice": compact_notice(envelope, args.description_chars),
                    "raw_output": raw_text[:1200],
                }
            )
            output.append(result)
            out_fh.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            out_fh.flush()
            write_summary(
                summary_path,
                summary_payload(
                    output,
                    args.sample_size,
                    args.startup_seconds,
                    started,
                    args.source_ledger_generation,
                    stopped_early=False,
                ),
            )

    summary = summary_payload(
        output,
        args.sample_size,
        args.startup_seconds,
        started,
        args.source_ledger_generation,
        stopped_early=stopped_early,
    )
    write_summary(summary_path, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
