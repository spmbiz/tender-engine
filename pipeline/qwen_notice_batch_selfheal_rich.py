#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os

import qwen_notice_batch_selfheal as base

RICH_PROMPT_VERSION = "qwen-batch-high-recall-business-fit-v3-rich"
RICH_CLASSIFIER_VERSION = "qwen3-4b-q4km-batch-selfheal-v2-rich"
MIN_CONTEXT_CHARS = max(900, int(os.getenv("QWEN_RICH_MIN_CONTEXT_CHARS", "1600")))
MAX_FIELD_CHARS = max(120, int(os.getenv("QWEN_RICH_FIELD_CHARS", "320")))


def compact_text(value, limit: int) -> str:
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
    return text[:limit]


def rich_description(row, requested_chars: int) -> str:
    n = base.notice(row)
    budget = max(MIN_CONTEXT_CHARS, int(requested_chars or 0))
    parts = []
    primary = compact_text(n.get("description"), max(500, budget // 2))
    if primary:
        parts.append("DESC: " + primary)
    for label, key in (
        ("LOTS", "lots"),
        ("ELIGIBILITY", "notice_eligibility"),
        ("AWARD", "award_criteria"),
        ("SUBCONTRACT", "subcontracting"),
    ):
        value = compact_text(n.get(key), MAX_FIELD_CHARS)
        if value:
            parts.append(label + ": " + value)
    text = " | ".join(parts)
    if len(text) > budget:
        text = text[:budget] + "…"
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


def rich_guard(decoded, row):
    # Reuse all existing deterministic safety calibration while letting those
    # guards see the same rich evidence the model sees. This changes routing
    # context only; it does not invent DCE facts or promote notice-only finals.
    clone = copy.deepcopy(row)
    if isinstance(clone.get("notice"), dict):
        clone["notice"]["description"] = rich_description(row, MIN_CONTEXT_CHARS)
    else:
        clone["description"] = rich_description(row, MIN_CONTEXT_CHARS)
    return _original_guard(decoded, clone)


base.PROMPT_VERSION = RICH_PROMPT_VERSION
base.CLASSIFIER_VERSION = RICH_CLASSIFIER_VERSION
base.compact = rich_compact
base.deterministic_guard = rich_guard

if __name__ == "__main__":
    base.main()
