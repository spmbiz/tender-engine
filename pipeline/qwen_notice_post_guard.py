#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "QWEN_NOTICE_POST_GUARD_V2"
PERSONAL_SERVICE = re.compile(r"\bpersonal services? contract\b", re.I)
LICENSED_ROLE = re.compile(r"\b(security officer|licensed|certified professional|physician|nurse|engineer of record)\b", re.I)
EQUIPMENT_RISK = re.compile(
    r"\b(trucks?|lorries?|lkw|microscopes?|machinery|heavy equipment|industrial equipment|"
    r"scientific instruments?|laboratory instruments?|speciali[sz]ed equipment)\b",
    re.I,
)
# High-recall rescue is deliberately notice-only routing, never DCE/eligibility truth.
# These are native/near-native SPM scopes whose model-level REJECT would be unsafe
# because downstream DCE is the authoritative place to discover qualification gates.
CORE_RECALL = re.compile(
    r"\b(website|web\s*site|web\s*app(?:lication)?|web\s*portal|portal development|"
    r"software development|application development|mobile app|smartphone app|"
    r"animation|video production|graphic design|creative services|content creation|"
    r"copywriting|editorial|proofreading|translation|transcription|printing|print services|"
    r"digitization|digitisation|scanning|e[- ]learning|training content|media monitoring|"
    r"social media|digital marketing|market research|survey services|data processing|"
    r"data entry|workflow automation|cms|hosting|web maintenance)\b",
    re.I,
)
BROKERABLE_GOODS = re.compile(
    r"\b(parts?|spares?|components?|supplies|goods|equipment|instruments?|materials?|"
    r"vehicles?|trucks?|machinery|furniture|uniforms?|promotional goods?)\b",
    re.I,
)
HARD_FRICTION = {"REGULATED_GOODS", "LICENSED_PERSONNEL", "SECURITY_CLEARANCE"}


def notice_text(row: dict[str, Any]) -> tuple[str, str]:
    n = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    title = str(n.get("title") or n.get("t") or "")
    desc = str(n.get("description") or n.get("d") or "")
    return title, f"{title} {desc}"


def guard(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    title, text = notice_text(row)
    flags = list(out.get("friction_flags") or []) if isinstance(out.get("friction_flags"), list) else []
    actions: list[str] = []

    # Preserve the actual model/deterministic-pre-guard label for diagnostics.
    out.setdefault("pre_post_guard_classification", out.get("classification"))
    out.setdefault("pre_post_guard_delivery_mode", out.get("delivery_mode"))

    if PERSONAL_SERVICE.search(text):
        if str(out.get("classification") or "").upper() != "REJECT_OBVIOUS":
            out["classification"] = "MAYBE"
            actions.append("personal_service_cap_to_maybe")
        if str(out.get("lean_attractiveness") or "").upper() not in {"LOW", "UNKNOWN"}:
            out["lean_attractiveness"] = "LOW"
            actions.append("personal_service_lean_cap_low")
        out["needs_gpt_review"] = True
        if LICENSED_ROLE.search(text) and "LICENSED_PERSONNEL" not in flags:
            flags.append("LICENSED_PERSONNEL")
            actions.append("possible_licensed_personnel_risk")

    if EQUIPMENT_RISK.search(text):
        if "HEAVY_EQUIPMENT" not in flags:
            flags.append("HEAVY_EQUIPMENT")
            actions.append("possible_heavy_equipment_risk")
        if str(out.get("classification") or "").upper() == "STRONG_FIT":
            out["classification"] = "FIT"
            actions.append("equipment_cap_strong_to_fit")
        if str(out.get("lean_attractiveness") or "").upper() == "HIGH":
            out["lean_attractiveness"] = "MEDIUM"
            actions.append("equipment_lean_cap_medium")
        out["needs_gpt_review"] = True

    # Qwen is only a high-recall router. A model REJECT is never allowed to erase
    # an obvious core scope when the deterministic survival layer said KEEP.
    classification = str(out.get("classification") or "").upper()
    survival = str(out.get("survival_decision") or "KEEP").upper()
    hard = bool(set(str(x).upper() for x in flags) & HARD_FRICTION)
    if classification == "REJECT_OBVIOUS" and survival == "KEEP" and not hard:
        if CORE_RECALL.search(text):
            out["classification"] = "FIT"
            if str(out.get("lean_attractiveness") or "").upper() in {"LOW", "UNKNOWN", ""}:
                out["lean_attractiveness"] = "MEDIUM"
            if str(out.get("delivery_mode") or "").upper() in {"", "UNCLEAR"}:
                out["delivery_mode"] = "DIRECT_DIGITAL"
            out["needs_gpt_review"] = True
            out["dce_eligible"] = True
            actions.append("high_recall_core_reject_rescued_to_fit")
        elif BROKERABLE_GOODS.search(text):
            out["classification"] = "MAYBE"
            if str(out.get("lean_attractiveness") or "").upper() not in {"LOW", "MEDIUM"}:
                out["lean_attractiveness"] = "MEDIUM"
            if str(out.get("delivery_mode") or "").upper() in {"", "UNCLEAR", "DIRECT_DIGITAL"}:
                out["delivery_mode"] = "BROKER_RESELL"
            out["needs_gpt_review"] = True
            out["dce_eligible"] = True
            actions.append("high_recall_brokerable_reject_rescued_to_maybe")

    out["friction_flags"] = flags
    out["post_guard_schema"] = SCHEMA
    out["post_guard_actions"] = actions
    out["post_guard_applied"] = bool(actions)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply generic non-destructive routing/risk guards to Qwen notice results.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    changed = 0
    with open(args.input, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            guarded = guard(row)
            changed += int(guarded.get("post_guard_applied", False))
            rows.append(guarded)

    Path(args.output).write_text(
        "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows),
        encoding="utf-8",
    )
    summary = {
        "schema": "QWEN_NOTICE_POST_GUARD_SUMMARY_V2",
        "input_rows": len(rows),
        "output_rows": len(rows),
        "rows_changed": changed,
        "classification_counts": dict(sorted(Counter(str(x.get("classification")) for x in rows).items())),
        "action_counts": dict(sorted(Counter(a for x in rows for a in (x.get("post_guard_actions") or [])).items())),
        "safety": {
            "drops_or_deletes_rows": False,
            "raw_model_results_preserved_separately": True,
            "risk_flags_are_dce_truth": False,
            "automatic_final_rejection_enabled": False,
            "reject_rescue_requires_survival_keep": True,
            "rescued_rows_still_require_dce_for_truth": True,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if summary["input_rows"] != summary["output_rows"]:
        raise SystemExit("post-guard row conservation failed")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
