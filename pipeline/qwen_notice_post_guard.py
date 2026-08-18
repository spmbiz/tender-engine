#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "QWEN_NOTICE_POST_GUARD_V4"
PERSONAL_SERVICE = re.compile(r"\bpersonal services? contract\b", re.I)
LICENSED_ROLE = re.compile(r"\b(security officer|licensed|certified professional|physician|nurse|engineer of record)\b", re.I)
EQUIPMENT_RISK = re.compile(
    r"\b(trucks?|lorries?|lkw|microscopes?|machinery|heavy equipment|industrial equipment|"
    r"scientific instruments?|laboratory instruments?|speciali[sz]ed equipment)\b",
    re.I,
)
CORE_RECALL = re.compile(
    r"\b(website|web\s*site|web\s*app(?:lication)?|web\s*portal|portal development|"
    r"software development|application development|mobile app|smartphone app|"
    r"animation|video production|graphic design|creative services|content creation|"
    r"copywriting|editorial|proofreading|translation|transcription|printing|print services|"
    r"digitization|digitisation|scanning|e[- ]learning|training content|media monitoring|"
    r"social media|digital marketing|market research|survey services|data processing|"
    r"data entry|workflow automation|cms|hosting|web maintenance|"
    r"aplikacj\w*\s+web(?:ow\w*)?)\b",
    re.I,
)
BROKERABLE_GOODS = re.compile(
    r"\b(parts?|spares?|components?|supplies|goods|equipment|instruments?|materials?|"
    r"vehicles?|trucks?|machinery|furniture|uniforms?|promotional goods?)\b",
    re.I,
)
HARD_FRICTION = {"REGULATED_GOODS", "LICENSED_PERSONNEL", "SECURITY_CLEARANCE"}


def candidate_id(row: dict[str, Any]) -> str:
    n = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    return str(
        row.get("canonical_notice_id")
        or row.get("candidate_id")
        or n.get("canonical_notice_id")
        or n.get("candidate_id")
        or n.get("notice_id")
        or n.get("id")
        or ""
    ).strip()


def _open_queue(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def load_notice_context(path: Path | None) -> dict[str, dict[str, Any]]:
    """Index the exact shard queue by canonical candidate identity.

    No fuzzy aliases are permitted here. The post-guard may use scope text only
    when the classifier result ID exactly matches one and only one source row.
    Duplicate IDs fail closed because attaching the wrong notice text could
    incorrectly change routing priority.
    """
    if path is None:
        return {}
    index: dict[str, dict[str, Any]] = {}
    with _open_queue(path) as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                continue
            cid = candidate_id(row)
            if not cid:
                continue
            if cid in index:
                raise SystemExit(f"duplicate candidate id in post-guard queue context: {cid}")
            index[cid] = row
    return index


def notice_text(row: dict[str, Any], context: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return title/scope text from the exact source context when available.

    Qwen raw results intentionally contain classification fields, not the full
    notice. Production shards created by build_qwen_shadow_shards.py are compact
    top-level notice records, so support both nested and top-level shapes.
    """
    source = context if isinstance(context, dict) else row
    n = source.get("notice") if isinstance(source.get("notice"), dict) else source
    title = str(n.get("title") or n.get("t") or "")
    desc = str(n.get("description") or n.get("d") or "")
    category = str(n.get("cpv_or_category") or n.get("category") or "")
    procedure = str(n.get("procedure") or "")
    return title, " ".join(x for x in (title, desc, category, procedure) if x)


def guard(row: dict[str, Any], notice_context: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(row)
    _title, text = notice_text(row, notice_context)
    flags = list(out.get("friction_flags") or []) if isinstance(out.get("friction_flags"), list) else []
    actions: list[str] = []

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

    classification = str(out.get("classification") or "").upper()
    survival = str(out.get("survival_decision") or "KEEP").upper()
    hard = bool(set(str(x).upper() for x in flags) & HARD_FRICTION)
    lean = str(out.get("lean_attractiveness") or "").upper()
    route = str(out.get("delivery_mode") or "").upper()
    core = bool(CORE_RECALL.search(text))

    if classification == "REJECT_OBVIOUS" and survival == "KEEP" and not hard:
        if core:
            out["classification"] = "FIT"
            if lean in {"LOW", "UNKNOWN", ""}:
                out["lean_attractiveness"] = "MEDIUM"
            if route in {"", "UNCLEAR"}:
                out["delivery_mode"] = "DIRECT_DIGITAL"
            out["needs_gpt_review"] = True
            out["dce_eligible"] = True
            actions.append("high_recall_core_reject_rescued_to_fit")
        elif BROKERABLE_GOODS.search(text):
            out["classification"] = "MAYBE"
            if lean not in {"LOW", "MEDIUM"}:
                out["lean_attractiveness"] = "MEDIUM"
            if route in {"", "UNCLEAR", "DIRECT_DIGITAL"}:
                out["delivery_mode"] = "BROKER_RESELL"
            out["needs_gpt_review"] = True
            out["dce_eligible"] = True
            actions.append("high_recall_brokerable_reject_rescued_to_maybe")

    classification = str(out.get("classification") or "").upper()
    lean = str(out.get("lean_attractiveness") or "").upper()
    route = str(out.get("delivery_mode") or "").upper()
    if (
        classification == "MAYBE"
        and survival == "KEEP"
        and not hard
        and core
        and lean == "HIGH"
        and route == "DIRECT_DIGITAL"
    ):
        out["classification"] = "FIT"
        out["needs_gpt_review"] = True
        out["dce_eligible"] = True
        actions.append("high_recall_core_high_direct_maybe_promoted_to_fit")

    out["friction_flags"] = flags
    out["post_guard_schema"] = SCHEMA
    out["post_guard_actions"] = actions
    out["post_guard_applied"] = bool(actions)
    out["post_guard_notice_context_used"] = bool(notice_context)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply non-destructive routing/risk guards to Qwen notice results.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--queue", help="Exact source shard/fixture used by Qwen; joined by exact candidate ID only.")
    args = ap.parse_args()

    context = load_notice_context(Path(args.queue)) if args.queue else {}
    rows: list[dict[str, Any]] = []
    changed = 0
    context_matches = 0
    context_misses = 0
    seen_result_ids: set[str] = set()
    with open(args.input, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            cid = candidate_id(row)
            if cid:
                if cid in seen_result_ids:
                    raise SystemExit(f"duplicate candidate id in post-guard results: {cid}")
                seen_result_ids.add(cid)
            source = context.get(cid) if cid else None
            if args.queue:
                if source is not None:
                    context_matches += 1
                else:
                    context_misses += 1
            guarded = guard(row, source)
            changed += int(guarded.get("post_guard_applied", False))
            rows.append(guarded)

    Path(args.output).write_text(
        "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows),
        encoding="utf-8",
    )
    summary = {
        "schema": "QWEN_NOTICE_POST_GUARD_SUMMARY_V4",
        "input_rows": len(rows),
        "output_rows": len(rows),
        "rows_changed": changed,
        "queue_context_rows": len(context),
        "context_matches": context_matches,
        "context_misses": context_misses,
        "classification_counts": dict(sorted(Counter(str(x.get("classification")) for x in rows).items())),
        "action_counts": dict(sorted(Counter(a for x in rows for a in (x.get("post_guard_actions") or [])).items())),
        "safety": {
            "drops_or_deletes_rows": False,
            "raw_model_results_preserved_separately": True,
            "automatic_final_rejection_enabled": False,
            "queue_context_join_is_exact_candidate_id_only": True,
            "duplicate_queue_or_result_ids_fail_closed": True,
            "context_miss_does_not_guess": True,
            "reject_rescue_requires_survival_keep": True,
            "maybe_to_fit_requires_core_high_direct_keep": True,
            "rescued_rows_still_require_dce_for_truth": True,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if summary["input_rows"] != summary["output_rows"]:
        raise SystemExit("post-guard row conservation failed")
    if args.queue and context_misses:
        raise SystemExit(f"post-guard exact context join failed for {context_misses} result rows")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
