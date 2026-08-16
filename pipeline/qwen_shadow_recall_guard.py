#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "QWEN_SHADOW_GUARDED_CLASSIFICATION_V1"
SUMMARY_SCHEMA = "QWEN_SHADOW_RECALL_GUARD_SUMMARY_V1"

# Strong title/scope signals only. This layer is intentionally conservative:
# it may downgrade ranking bands or correct delivery mode, but never drops a row.
PHYSICAL_GOODS = re.compile(
    r"\b(parts?|spares?|equipment|supplies?|vehicle|truck|lorry|lkw|microscopes?|filters?|reactors?|furniture|machinery|components?|instruments?|devices?)\b",
    re.I,
)
REGULATED = re.compile(
    r"\b(methylphenidate|controlled substance|prescription drug|pharmaceutical|narcotic|ammunition|firearms?|explosives?|radioactive|nuclear material)\b",
    re.I,
)
HEAVY_ONSITE = re.compile(
    r"\b(construction|civil works?|installation work|hvac|heating|ventilation|air[- ]conditioning|mold (?:mitigation|remediation|abatement)|chillers?|building works?|architect led design team)\b",
    re.I,
)
DIRECT_DIGITAL = re.compile(
    r"\b(website|web ?app|web portal|software|saas|digital platform|application development|mobile app|animation|video production|graphic design|content creation|transcription|cms|workflow automation|e[- ]learning|online training|data processing)\b",
    re.I,
)
# Match subcontract, subcontractor(s), subcontracting, subcontracted, etc.
INDIRECT_PATH = re.compile(
    r"\b(subcontract(?:or(?:s)?|ing|ed|s)?|third[- ]party|consortium|resell|broker|supplier|vendor)\b",
    re.I,
)
PERSONAL_SERVICE = re.compile(r"\bpersonal services? contract\b", re.I)


def text_of(row: dict[str, Any]) -> tuple[str, str]:
    notice = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    title = str(notice.get("title") or "")
    scope = " ".join(
        str(notice.get(k) or "")
        for k in ("title", "description", "cpv_or_category", "procedure")
    )
    # Model reason is not authoritative procurement evidence, but it may expose the model's own
    # delivery-route rationale. It is used only as a recall-preserving hint, never as a final gate.
    model_reason = str(row.get("reason") or "")
    if model_reason:
        scope = f"{scope} {model_reason}"
    return title, scope


def apply_guard(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    model_class = str(row.get("classification") or "MAYBE").upper()
    model_mode = str(row.get("delivery_mode") or "UNCLEAR").upper()
    classification = model_class
    mode = model_mode
    title, scope = text_of(row)
    actions: list[str] = []

    physical = bool(PHYSICAL_GOODS.search(title)) or bool(PHYSICAL_GOODS.search(scope[:900]))
    regulated = bool(REGULATED.search(title)) or bool(REGULATED.search(scope[:1200]))
    heavy = bool(HEAVY_ONSITE.search(title)) or bool(HEAVY_ONSITE.search(scope[:1000]))
    clearly_digital = bool(DIRECT_DIGITAL.search(title)) or bool(DIRECT_DIGITAL.search(scope[:1200]))
    indirect = bool(INDIRECT_PATH.search(scope)) or model_mode in {"BROKER_RESELL", "SUBCONTRACTABLE", "MIXED"}
    personal = bool(PERSONAL_SERVICE.search(title))

    # Regulated scopes remain visible but cannot rank as a strong/easy fit from notice metadata.
    if regulated:
        if classification != "MAYBE":
            classification = "MAYBE"
            actions.append("regulated_scope_cap_to_maybe")
        if mode in {"DIRECT_DIGITAL", "AI_ENABLED", "UNCLEAR"}:
            mode = "BROKER_RESELL"
            actions.append("regulated_scope_mode_to_broker_resell")

    # Commercial physical goods may be sourceable/brokerable. Never auto-reject them here.
    elif physical and not clearly_digital:
        if mode in {"DIRECT_DIGITAL", "AI_ENABLED", "UNCLEAR"}:
            mode = "BROKER_RESELL"
            actions.append("physical_goods_mode_to_broker_resell")
        if classification == "STRONG_FIT":
            classification = "FIT"
            actions.append("physical_goods_cap_strong_to_fit")
        elif classification == "REJECT_OBVIOUS":
            classification = "MAYBE"
            actions.append("physical_goods_reject_to_maybe_for_broker_recall")

    # Specialist onsite work can remain interesting through a partner, but is not direct digital.
    if heavy and not personal:
        if mode == "DIRECT_DIGITAL":
            mode = "SUBCONTRACTABLE"
            actions.append("heavy_onsite_mode_to_subcontractable")
        if classification == "STRONG_FIT":
            classification = "FIT"
            actions.append("heavy_onsite_cap_strong_to_fit")

    # Reserve STRONG_FIT for scopes with a clear lean/direct-digital signal.
    if classification == "STRONG_FIT" and not clearly_digital:
        classification = "FIT"
        actions.append("strong_fit_requires_clear_digital_signal")

    # If the notice/model itself exposes an indirect delivery route, a destructive-looking reject
    # is too risky for the user's high-recall policy. Keep it as MAYBE for later GPT/DCE review.
    if classification == "REJECT_OBVIOUS" and indirect and not personal:
        classification = "MAYBE"
        actions.append("reject_to_maybe_due_indirect_delivery_path")

    out["model_classification"] = model_class
    out["model_delivery_mode"] = model_mode
    out["classification"] = classification
    out["delivery_mode"] = mode
    out["recall_guard_actions"] = actions
    out["recall_guard_applied"] = bool(actions)
    out["guard_schema"] = SCHEMA
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    changed = 0
    with open(args.input, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            guarded = apply_guard(row)
            changed += int(guarded["recall_guard_applied"])
            rows.append(guarded)

    Path(args.output).write_text(
        "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8",
    )
    model_counts = Counter(str(r.get("model_classification")) for r in rows)
    guarded_counts = Counter(str(r.get("classification")) for r in rows)
    summary = {
        "schema": SUMMARY_SCHEMA,
        "rows": len(rows),
        "rows_changed": changed,
        "model_counts": dict(sorted(model_counts.items())),
        "guarded_counts": dict(sorted(guarded_counts.items())),
        "safety": {
            "drops_or_deletes_rows": False,
            "automatic_rejection_enabled": False,
            "purpose": "ranking/mode correction only; GPT+DCE remain truth",
        },
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
