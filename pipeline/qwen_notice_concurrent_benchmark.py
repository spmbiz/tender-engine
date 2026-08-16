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
    SYSTEM, PROMPT_VERSION, candidate_id, compact_notice, deterministic_sample,
    extract_object, iter_jsonl, normalize, post_json, user_prompt,
)


def classify_one(envelope: dict[str, Any], *, server: str, model: str, timeout: int, max_tokens: int) -> dict[str, Any]:
    cid = candidate_id(envelope)
    t0 = time.monotonic()
    parse_error = None
    raw_obj = None
    raw_text = ""
    usage: dict[str, Any] = {}
    try:
        response = post_json(server, {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt(envelope)},
            ],
            "temperature": 0.1,
            "top_p": 0.8,
            "max_tokens": max_tokens,
            "stream": False,
        }, timeout)
        raw_text = str(response["choices"][0]["message"]["content"])
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        raw_obj = extract_object(raw_text)
        if raw_obj is None:
            parse_error = "invalid_json"
    except Exception as exc:
        parse_error = f"request_error:{type(exc).__name__}"
    result = normalize(raw_obj, parse_error)
    result.update({
        "schema": "QWEN_NOTICE_CONCURRENT_SHADOW_V1",
        "canonical_notice_id": cid,
        "classifier_model": model,
        "classifier_prompt_version": PROMPT_VERSION,
        "latency_seconds": round(time.monotonic() - t0, 3),
        "usage": usage,
        "notice": compact_notice(envelope),
        "raw_output": raw_text[:2000],
    })
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--sample-size", type=int, default=24)
    ap.add_argument("--server", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max-tokens", type=int, default=100)
    ap.add_argument("--startup-seconds", type=float, default=0.0)
    args = ap.parse_args()
    if args.concurrency not in {1, 2, 4}:
        raise SystemExit("concurrency must be 1, 2, or 4")

    sample = deterministic_sample(iter_jsonl(Path(args.queue)), args.sample_size)
    started = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(classify_one, row, server=args.server, model=args.model, timeout=args.timeout, max_tokens=args.max_tokens): candidate_id(row)
            for row in sample
        }
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                results[cid] = fut.result()
            except Exception as exc:
                results[cid] = {
                    "schema": "QWEN_NOTICE_CONCURRENT_SHADOW_V1",
                    "canonical_notice_id": cid,
                    "classification": "MAYBE",
                    "confidence": 0.0,
                    "delivery_mode": "UNCLEAR",
                    "novelty_or_unusual_flag": True,
                    "reason": "Concurrent worker failed; high-recall fallback retained notice.",
                    "parse_error": f"future_error:{type(exc).__name__}",
                }

    ordered = [results[candidate_id(row)] for row in sample]
    elapsed = time.monotonic() - started
    Path(args.out).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in ordered), encoding="utf-8")
    counts = Counter(str(x.get("classification")) for x in ordered)
    parse_errors = sum(1 for x in ordered if x.get("parse_error"))
    summary = {
        "schema": "QWEN_NOTICE_CONCURRENT_BENCHMARK_SUMMARY_V1",
        "model": args.model,
        "prompt_version": PROMPT_VERSION,
        "concurrency": args.concurrency,
        "sample_size": len(ordered),
        "startup_seconds": args.startup_seconds,
        "inference_seconds": round(elapsed, 3),
        "seconds_per_notice_wall": round(elapsed / len(ordered), 3) if ordered else None,
        "notices_per_second": round(len(ordered) / elapsed, 4) if elapsed and ordered else None,
        "parse_errors": parse_errors,
        "classification_counts": dict(sorted(counts.items())),
        "row_conservation_pass": len(ordered) == len(sample) == len(set(x["canonical_notice_id"] for x in ordered)),
        "safety": "SHADOW_ONLY; any request/future error falls back to MAYBE and no notice is deleted.",
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
