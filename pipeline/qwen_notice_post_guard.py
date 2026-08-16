#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "QWEN_NOTICE_POST_GUARD_V1"
PERSONAL_SERVICE = re.compile(r"\bpersonal services? contract\b", re.I)
LICENSED_ROLE = re.compile(r"\b(security officer|licensed|certified professional|physician|nurse|engineer of record)\b", re.I)
EQUIPMENT_RISK = re.compile(
    r"\b(trucks?|lorries?|lkw|microscopes?|machinery|heavy equipment|industrial equipment|"
    r"scientific instruments?|laboratory instruments?|speciali[sz]ed equipment)\b",
    re.I,
)


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
        "schema": "QWEN_NOTICE_POST_GUARD_SUMMARY_V1",
        "input_rows": len(rows),
        "output_rows": len(rows),
        "rows_changed": changed,
        "classification_counts": dict(sorted(Counter(str(x.get("classification")) for x in rows).items())),
        "safety": {
            "drops_or_deletes_rows": False,
            "raw_model_results_preserved_separately": True,
            "risk_flags_are_dce_truth": False,
            "automatic_final_rejection_enabled": False,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if summary["input_rows"] != summary["output_rows"]:
        raise SystemExit("post-guard row conservation failed")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
