#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ALLOWED = {"STRONG_FIT", "FIT", "MAYBE", "REJECT_OBVIOUS"}
DELIVERY_MODES = {"DIRECT_DIGITAL", "AI_ENABLED", "SUBCONTRACTABLE", "BROKER_RESELL", "MIXED", "UNCLEAR"}
PROMPT_VERSION = "qwen-notice-high-recall-v1"

SYSTEM = """You are a HIGH-RECALL public-tender opportunity classifier for a lean Belgian SME.
The business may deliver directly, use AI/software automation, subcontract specialists, form a consortium, broker/resell goods or services, or combine these modes.
Your job is triage, NOT eligibility adjudication. Notice metadata cannot prove DCE gates.
Prefer false positives over false negatives. If scope is ambiguous, unusual, niche, potentially subcontractable/brokerable/resellable, or information is insufficient, choose MAYBE rather than REJECT_OBVIOUS.
REJECT_OBVIOUS is reserved for clearly unsuitable work with no plausible lean direct, AI-enabled, subcontracted, consortium, broker/resell or operational path.
Never call anything GREEN or SUPERGREEN.
Return one JSON object only. /no_think"""


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
    return str(row.get("canonical_notice_id") or (row.get("notice") or {}).get("candidate_id") or "").strip()


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


def compact_notice(envelope: dict[str, Any]) -> dict[str, Any]:
    row = envelope.get("notice") if isinstance(envelope.get("notice"), dict) else envelope
    description = str(row.get("description") or "")
    if len(description) > 5000:
        description = description[:5000] + " …[truncated]"
    return {
        "candidate_id": str(row.get("candidate_id") or envelope.get("canonical_notice_id") or ""),
        "source": row.get("source"),
        "country": row.get("country"),
        "buyer": row.get("buyer"),
        "title": row.get("title"),
        "description": description,
        "cpv_or_category": row.get("cpv_or_category"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "deadline": row.get("deadline"),
        "procedure": row.get("procedure"),
        "lots": row.get("lots"),
        "notice_eligibility": row.get("notice_eligibility"),
        "subcontracting": row.get("subcontracting"),
    }


def user_prompt(row: dict[str, Any]) -> str:
    return """Classify this notice into exactly one of STRONG_FIT, FIT, MAYBE, REJECT_OBVIOUS.
Use high recall. Digital training, web portals, IT/ICT, software, data, design, video, content, printing, consulting, operational services, and plausible broker/resell/subcontract opportunities must not be rejected merely because delivery details are uncertain.
Output JSON only with keys:
classification, confidence (0..1), novelty_or_unusual_flag (boolean), delivery_mode (DIRECT_DIGITAL|AI_ENABLED|SUBCONTRACTABLE|BROKER_RESELL|MIXED|UNCLEAR), reason (max 30 words).
/no_think

NOTICE:
""" + json.dumps(compact_notice(row), ensure_ascii=False)


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
            "reason": "Model output was unavailable or invalid; high-recall fallback keeps notice for review.",
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
    reason = " ".join(str(raw.get("reason") or "").split())[:500]
    return {
        "classification": classification,
        "confidence": confidence,
        "novelty_or_unusual_flag": bool(raw.get("novelty_or_unusual_flag", False)),
        "delivery_mode": mode,
        "reason": reason,
        "parse_error": parse_error,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--server", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--sample-size", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--startup-seconds", type=float, default=0.0)
    args = ap.parse_args()

    sample = deterministic_sample(iter_jsonl(Path(args.queue)), args.sample_size)
    output: list[dict[str, Any]] = []
    started = time.monotonic()
    for envelope in sample:
        cid = candidate_id(envelope)
        t0 = time.monotonic()
        parse_error = None
        raw_obj = None
        raw_text = ""
        try:
            response = post_json(
                args.server,
                {
                    "model": args.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user_prompt(envelope)},
                    ],
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "max_tokens": 220,
                    "stream": False,
                },
                args.timeout,
            )
            raw_text = str(response["choices"][0]["message"]["content"])
            raw_obj = extract_object(raw_text)
            if raw_obj is None:
                parse_error = "invalid_json"
        except Exception as exc:
            parse_error = f"request_error:{type(exc).__name__}"
        result = normalize(raw_obj, parse_error)
        result.update(
            {
                "schema": "QWEN_NOTICE_SHADOW_CLASSIFICATION_V1",
                "canonical_notice_id": cid,
                "classifier_model": args.model,
                "classifier_quant": "Q4_K_M",
                "classifier_prompt_version": PROMPT_VERSION,
                "classifier_version": "qwen3-4b-q4km-shadow-v1",
                "classified_at_epoch": int(time.time()),
                "latency_seconds": round(time.monotonic() - t0, 3),
                "notice": compact_notice(envelope),
                "raw_output": raw_text[:2000],
            }
        )
        output.append(result)

    elapsed = time.monotonic() - started
    counts = Counter(x["classification"] for x in output)
    parse_errors = sum(1 for x in output if x.get("parse_error"))
    summary = {
        "schema": "QWEN_NOTICE_SHADOW_SMOKE_SUMMARY_V1",
        "classifier_model": args.model,
        "classifier_quant": "Q4_K_M",
        "classifier_prompt_version": PROMPT_VERSION,
        "classifier_version": "qwen3-4b-q4km-shadow-v1",
        "sample_size": len(output),
        "startup_seconds": round(args.startup_seconds, 3),
        "inference_seconds": round(elapsed, 3),
        "notices_per_second": round(len(output) / elapsed, 4) if elapsed else None,
        "seconds_per_notice": round(elapsed / len(output), 3) if output else None,
        "parse_errors": parse_errors,
        "classification_counts": dict(sorted(counts.items())),
        "safety": "SHADOW_ONLY: outputs do not delete notices, decide eligibility, or establish DCE truth.",
    }
    Path(args.out).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in output), encoding="utf-8")
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
