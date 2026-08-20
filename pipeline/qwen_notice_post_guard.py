#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "QWEN_NOTICE_POST_GUARD_V5_EXACT_CONTEXT"
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
        or n.get("i")
        or ""
    ).strip()


def _open_queue(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    with _open_queue(path) as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception as exc:
                raise SystemExit(f"invalid JSON in post-guard input {path}:{lineno}: {type(exc).__name__}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"non-object JSON row in post-guard input {path}:{lineno}")
            yield row


def load_notice_context(path: Path | None) -> dict[str, dict[str, Any]]:
    """Index one exact shard queue by canonical candidate identity.

    No fuzzy aliases are permitted here. Duplicate IDs fail closed because
    attaching the wrong notice text could incorrectly change routing priority.
    """
    if path is None:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in _iter_rows(path):
        cid = candidate_id(row)
        if not cid:
            raise SystemExit(f"missing candidate id in post-guard queue context: {path}")
        if cid in index:
            raise SystemExit(f"duplicate candidate id in post-guard queue context: {cid}")
        index[cid] = row
    return index


def discover_notice_context(root: Path, wanted_ids: set[str]) -> tuple[dict[str, dict[str, Any]], int]:
    """Recover exact source rows from the downloaded production shard set.

    The live workflow historically omitted ``--queue`` when invoking this guard.
    Instead of silently applying semantic rescue rules to truncated classifier
    echoes, find the source shard deterministically by exact candidate ID. Every
    matching row across every shard is scanned so duplicate identities fail
    closed rather than being hidden by filesystem order.
    """
    if not root.exists() or not root.is_dir():
        return {}, 0
    files = sorted(
        p for p in root.rglob("qwen-shadow-*.jsonl*")
        if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.gz"))
    )
    index: dict[str, dict[str, Any]] = {}
    for path in files:
        for row in _iter_rows(path):
            cid = candidate_id(row)
            if not cid or cid not in wanted_ids:
                continue
            if cid in index:
                raise SystemExit(f"duplicate candidate id across post-guard shard context: {cid}")
            index[cid] = row
    return index, len(files)


def notice_text(row: dict[str, Any], context: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return title/scope text from exact context, with compact aliases supported.

    Raw Qwen results embed a compact notice echo. Production source shards carry
    full top-level fields. ``k`` and ``p`` are the compact aliases for category
    and procedure and must remain usable for standalone fixtures/fallbacks.
    """
    source = context if isinstance(context, dict) else row
    n = source.get("notice") if isinstance(source.get("notice"), dict) else source
    title = str(n.get("title") or n.get("t") or "")
    desc = str(n.get("description") or n.get("d") or "")
    category = str(n.get("cpv_or_category") or n.get("category") or n.get("k") or "")
    procedure = str(n.get("procedure") or n.get("p") or "")
    return title, " ".join(x for x in (title, desc, category, procedure) if x)


def guard(
    row: dict[str, Any],
    notice_context: dict[str, Any] | None = None,
    *,
    context_source: str = "embedded_result",
) -> dict[str, Any]:
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
    out["post_guard_context_source"] = context_source if notice_context else "embedded_result"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply non-destructive routing/risk guards to Qwen notice results.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--queue", help="Exact source shard/fixture used by Qwen; joined by exact candidate ID only.")
    ap.add_argument(
        "--queue-root",
        help="Directory of source shards for exact-ID auto-discovery. If omitted, work/shards is used when present.",
    )
    args = ap.parse_args()

    input_rows = list(_iter_rows(Path(args.input)))
    seen_result_ids: set[str] = set()
    for row in input_rows:
        cid = candidate_id(row)
        if not cid:
            raise SystemExit("missing candidate id in post-guard results")
        if cid in seen_result_ids:
            raise SystemExit(f"duplicate candidate id in post-guard results: {cid}")
        seen_result_ids.add(cid)

    context: dict[str, dict[str, Any]] = {}
    context_source = "embedded_result"
    context_files = 0
    context_required = False
    if args.queue:
        context = load_notice_context(Path(args.queue))
        context_source = "explicit_queue"
        context_files = 1
        context_required = True
    else:
        root = Path(args.queue_root) if args.queue_root else Path("work/shards")
        if args.queue_root or root.exists():
            context, context_files = discover_notice_context(root, seen_result_ids)
            if context_files == 0:
                raise SystemExit(f"post-guard queue root contains no Qwen shard files: {root}")
            context_source = "auto_discovered_queue"
            context_required = True

    rows: list[dict[str, Any]] = []
    changed = 0
    context_matches = 0
    context_misses = 0
    for row in input_rows:
        cid = candidate_id(row)
        source = context.get(cid)
        if context_required:
            if source is not None:
                context_matches += 1
            else:
                context_misses += 1
        guarded = guard(row, source, context_source=context_source)
        changed += int(guarded.get("post_guard_applied", False))
        rows.append(guarded)

    if context_required and context_misses:
        raise SystemExit(f"post-guard exact context join failed for {context_misses} result rows")

    Path(args.output).write_text(
        "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows),
        encoding="utf-8",
    )
    summary = {
        "schema": "QWEN_NOTICE_POST_GUARD_SUMMARY_V5_EXACT_CONTEXT",
        "input_rows": len(rows),
        "output_rows": len(rows),
        "rows_changed": changed,
        "queue_context_rows": len(context),
        "queue_context_files": context_files,
        "context_source": context_source,
        "context_required": context_required,
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
            "production_context_auto_discovery_enabled": True,
            "production_context_miss_fails_closed": True,
            "compact_k_p_aliases_supported": True,
            "reject_rescue_requires_survival_keep": True,
            "maybe_to_fit_requires_core_high_direct_keep": True,
            "rescued_rows_still_require_dce_for_truth": True,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if summary["input_rows"] != summary["output_rows"]:
        raise SystemExit("post-guard row conservation failed")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
