#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import time
import urllib.error

import qwen_notice_batch_selfheal_core as base

RICH_PROMPT_VERSION = "qwen-batch-high-recall-business-fit-v3-rich"
# Keep the workflow's classifier-version contract stable; prompt-version is the
# semantic migration key and is enforced by the state merger below.
RICH_CLASSIFIER_VERSION = "qwen3-4b-q4km-batch-selfheal-v1"
MIN_CONTEXT_CHARS = max(1200, int(os.getenv("QWEN_RICH_MIN_CONTEXT_CHARS", "2200")))
MAX_FIELD_CHARS = max(120, int(os.getenv("QWEN_RICH_FIELD_CHARS", "320")))
TRANSPORT_RETRIES = max(0, min(3, int(os.getenv("QWEN_TRANSPORT_RETRIES", "1"))))
TRANSPORT_RETRY_BASE_SECONDS = max(0.0, min(5.0, float(os.getenv("QWEN_TRANSPORT_RETRY_BASE_SECONDS", "0.5"))))
TRANSIENT_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}


def compact_text(value, limit: int, *, preserve_tail: bool = False) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = str(value)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    if preserve_tail and limit >= 240:
        head = max(120, int(limit * 0.65))
        tail = max(80, limit - head - 3)
        return text[:head] + " … " + text[-tail:]
    return text[:limit]


def rich_description(row, requested_chars: int) -> str:
    n = base.notice(row)
    budget = max(MIN_CONTEXT_CHARS, int(requested_chars or 0))
    parts = []
    primary = compact_text(n.get("description"), max(700, budget // 2), preserve_tail=True)
    if primary:
        parts.append("DESC: " + primary)
    # Eligibility/subcontracting are recall-critical: they can turn a generic
    # title into a feasible broker/partner opportunity, or reveal the opposite.
    for label, key in (
        ("ELIGIBILITY", "notice_eligibility"),
        ("SUBCONTRACT", "subcontracting"),
        ("LOTS", "lots"),
        ("AWARD", "award_criteria"),
    ):
        value = compact_text(n.get(key), MAX_FIELD_CHARS, preserve_tail=True)
        if value:
            parts.append(label + ": " + value)
    text = " | ".join(parts)
    if len(text) > budget:
        # Preserve the tail of the complete evidence bundle too; otherwise the
        # last gate field is systematically sacrificed on long notices.
        head = max(700, int(budget * 0.72))
        tail = max(300, budget - head - 3)
        text = text[:head] + " … " + text[-tail:]
    return text


def rich_compact(row, description_chars: int):
    n = base.notice(row)
    return {
        "i": base.cid(row),
        "t": n.get("title"),
        "b": n.get("buyer"),
        "c": n.get("country"),
        "k": n.get("cpv_or_category"),
        "d": rich_description(row, description_chars),
        "v": n.get("estimated_value"),
        "y": n.get("currency"),
        "p": n.get("procedure"),
        "e": n.get("deadline") or n.get("deadline_utc"),
    }


_original_guard = base.deterministic_guard
_original_post_json = base.post_json


def rich_guard(decoded, row):
    # Reuse every existing deterministic safety calibration while showing those
    # guards the same evidence the semantic classifier sees. This is routing
    # context only; DCE remains authoritative and notice-only final verdicts stay
    # impossible.
    clone = copy.deepcopy(row)
    if isinstance(clone.get("notice"), dict):
        clone["notice"]["description"] = rich_description(row, MIN_CONTEXT_CHARS)
    else:
        clone["description"] = rich_description(row, MIN_CONTEXT_CHARS)
    return _original_guard(decoded, clone)


def _retryable_transport_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return int(getattr(exc, "code", 0) or 0) in TRANSIENT_HTTP
    return isinstance(
        exc,
        (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            json.JSONDecodeError,
        ),
    )


def retrying_post_json(url: str, payload: dict, timeout: int):
    """Retry transient server/transport failures before recursive batch splitting.

    A one-off timeout on an 8-row request used to immediately create an entire
    binary split tree. One bounded retry is dramatically cheaper than 2N-1
    follow-up requests while preserving the core self-heal fallback if the retry
    still fails. Permanent HTTP errors are never retried.
    """
    for retry_index in range(TRANSPORT_RETRIES + 1):
        try:
            return _original_post_json(url, payload, timeout)
        except Exception as exc:
            if retry_index >= TRANSPORT_RETRIES or not _retryable_transport_error(exc):
                raise
            delay = TRANSPORT_RETRY_BASE_SECONDS * (2**retry_index)
            print(
                "QWEN_TRANSPORT_RETRY "
                + json.dumps(
                    {
                        "retry": retry_index + 1,
                        "max_retries": TRANSPORT_RETRIES,
                        "error": type(exc).__name__,
                        "delay_seconds": round(delay, 3),
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            if delay:
                time.sleep(delay)
    raise AssertionError("unreachable transport retry loop")


base.PROMPT_VERSION = RICH_PROMPT_VERSION
base.CLASSIFIER_VERSION = RICH_CLASSIFIER_VERSION
base.compact = rich_compact
base.deterministic_guard = rich_guard
base.post_json = retrying_post_json

if __name__ == "__main__":
    base.main()
