#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pipeline.qwen_notice_shadow_classifier import (
    CLASSIFIER_VERSION,
    SYSTEM,
    PROMPT_VERSION,
    candidate_id,
    classifier_input_hash,
    compact_notice,
    deterministic_sample,
    extract_object,
    iter_jsonl,
    material_hash,
    normalize,
    post_json,
    user_prompt,
)

SCHEMA = "QWEN_NOTICE_CONCURRENT_SHADOW_V2"


def classify_one(
    envelope: dict[str, Any],
    *,
    server: str,
    model: str,
    timeout: int,
    max_tokens: int,
    description_chars: int,
    source_ledger_generation: str,
) -> dict[str, Any]:
    cid = candidate_id(envelope)
    t0 = time.monotonic()
    parse_error = None
    raw_obj = None
    raw_text = ""
    usage: dict[str, Any] = {}
    try:
        response = post_json(
            server,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user_prompt(envelope, description_chars)},
                ],
                "temperature": 0.1,
                "top_p": 0.8,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout,
        )
        raw_text = str(response["choices"][0]["message"]["content"])
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        raw_obj = extract_object(raw_text)
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
            "classifier_input_hash": classifier_input_hash(envelope, description_chars),
            "source_ledger_generation": source_ledger_generation,
            "classifier_model": model,
            "classifier_quant": "Q4_K_M",
            "classifier_prompt_version": PROMPT_VERSION,
            "classifier_version": f"{CLASSIFIER_VERSION}+concurrent-slots",
            "latency_seconds": round(time.monotonic() - t0, 3),
            "usage": usage,
            "notice": compact_notice(envelope, description_chars),
            "raw_output": raw_text[:1200],
        }
    )
    return result


def fallback(cid: str, envelope: dict[str, Any], reason: str, description_chars: int, source_generation: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "canonical_notice_id": cid,
        "input_material_fields_hash": material_hash(envelope),
        "classifier_input_hash": classifier_input_hash(envelope, description_chars),
        "source_ledger_generation": source_generation,
        "classifier_model": "Qwen/Qwen3-4B-GGUF:Q4_K_M",
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": PROMPT_VERSION,
        "classifier_version": f"{CLASSIFIER_VERSION}+concurrent-slots",
        "classification": "MAYBE",
        "confidence": 0.0,
        "delivery_mode": "UNCLEAR",
        "novelty_or_unusual_flag": True,
        "reason": "Concurrent worker failed; high-recall fallback retained notice.",
        "parse_error": reason,
        "notice": compact_notice(envelope, description_chars),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--sample-size", type=int, default=12)
    ap.add_argument("--server", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max-tokens", type=int, default=100)
    ap.add_argument("--description-chars", type=int, default=1800)
    ap.add_argument("--startup-seconds", type=float, default=0.0)
    ap.add_argument("--source-ledger-generation", default="UNKNOWN")
    args = ap.parse_args()
    if args.concurrency not in {1, 2, 4}:
        raise SystemExit("concurrency must be 1, 2, or 4")

    sample = deterministic_sample(iter_jsonl(Path(args.queue)), args.sample_size)
    by_id = {candidate_id(row): row for row in sample}
    started = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(
                classify_one,
                row,
                server=args.server,
                model=args.model,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                description_chars=args.description_chars,
                source_ledger_generation=args.source_ledger_generation,
            ): candidate_id(row)
            for row in sample
        }
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                results[cid] = fut.result()
            except Exception as exc:
                results[cid] = fallback(
                    cid,
                    by_id[cid],
                    f"future_error:{type(exc).__name__}",
                    args.description_chars,
                    args.source_ledger_generation,
                )

    ordered = [results[candidate_id(row)] for row in sample]
    elapsed = time.monotonic() - started
    Path(args.out).write_text(
        "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in ordered),
        encoding="utf-8",
    )
    counts = Counter(str(x.get("classification")) for x in ordered)
    parse_errors = sum(1 for x in ordered if x.get("parse_error"))
    summary = {
        "schema": "QWEN_NOTICE_CONCURRENT_BENCHMARK_SUMMARY_V2",
        "model": args.model,
        "classifier_version": f"{CLASSIFIER_VERSION}+concurrent-slots",
        "prompt_version": PROMPT_VERSION,
        "source_ledger_generation": args.source_ledger_generation,
        "concurrency": args.concurrency,
        "sample_size": len(ordered),
        "startup_seconds": args.startup_seconds,
        "inference_seconds": round(elapsed, 3),
        "seconds_per_notice_wall": round(elapsed / len(ordered), 3) if ordered else None,
        "notices_per_second": round(len(ordered) / elapsed, 4) if elapsed and ordered else None,
        "parse_errors": parse_errors,
        "classification_counts": dict(sorted(counts.items())),
        "row_conservation_pass": len(ordered) == len(sample) == len(set(x["canonical_notice_id"] for x in ordered)),
        "data_safety": {
            "shadow_only": True,
            "drops_or_deletes_notices": False,
            "automatic_rejection_enabled": False,
            "request_or_future_error_becomes": "MAYBE",
        },
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
