#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from auto_select_dce import business_fit, portal_key
from build_matrix import SUPPORTED, resolve_dce_portal
from dce_attempt_ledger import load_attempt_index, was_attempted

SCHEMA = "FRESH_DIGITAL_EXPRESS_SELECTION_V1"
SUMMARY_SCHEMA = "FRESH_DIGITAL_EXPRESS_SUMMARY_V2"
CORE_CLASSES = {
    "SPM_WEB",
    "SPM_DESIGN",
    "SPM_VIDEO",
    "SPM_CONTENT_MARKETING",
    "SPM_TRANSCRIPTION",
    "SPM_SOFTWARE_AUTOMATION",
    "SPM_PRINT_MIDDLEMAN",
    "SPM_DIGITAL_TRAINING",
}
# Precision lane only: obvious market-sounding / informational notices must never
# consume scarce express DCE capacity. They remain untouched in the canonical
# Qwen/ledger universe, so this is routing suppression, not notice deletion.
NON_BID_RX = re.compile(
    r"\b(preliminary market consultation|prior information notice|pin\b|request for information|rfi\b|"
    r"sources sought|market sounding|market consultation|industry day|supplier engagement|"
    r"expression of interest only|future opportunity|contract award notice|award notice|"
    r"notice of award|intention to award|voluntary ex ante transparency)\b",
    re.I,
)


def open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")


def iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    with open_text(path) as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def notice(row: dict[str, Any]) -> dict[str, Any]:
    n = row.get("notice")
    return n if isinstance(n, dict) else row


def candidate_id(row: dict[str, Any]) -> str:
    n = notice(row)
    return str(row.get("canonical_notice_id") or n.get("candidate_id") or n.get("notice_id") or n.get("id") or "").strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get("material_fields_hash") or row.get("input_material_fields_hash") or "").strip()


def parse_deadline(row: dict[str, Any]):
    n = notice(row)
    raw = n.get("deadline") or n.get("deadline_utc") or row.get("deadline") or row.get("deadline_utc")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def flat_notice(row: dict[str, Any]) -> dict[str, Any]:
    n = dict(notice(row))
    cid = candidate_id(row)
    if cid:
        n.setdefault("candidate_id", cid)
    if row.get("canonical_notice_id"):
        n.setdefault("canonical_notice_id", row.get("canonical_notice_id"))
    for key in ("portal", "source", "source_family", "country", "buyer", "title", "description", "cpv_or_category", "procedure", "notice_type", "type", "deadline", "deadline_utc"):
        if not n.get(key) and row.get(key):
            n[key] = row.get(key)
    return n


def is_obvious_non_bid(n: dict[str, Any]) -> bool:
    title = str(n.get("title") or "")
    procedure = str(n.get("procedure") or "")
    notice_type = str(n.get("notice_type") or n.get("type") or "")
    probe = " ".join((title, procedure, notice_type))
    return bool(NON_BID_RX.search(probe))


def attempt_probe(row: dict[str, Any], source_run: str) -> dict[str, Any]:
    n = flat_notice(row)
    return {
        "candidate_id": candidate_id(row),
        "material_fields_hash": material_hash(row),
        "wide_read_run_id": str(source_run),
        "title": n.get("title"),
        "buyer": n.get("buyer"),
        "provider": n.get("portal") or n.get("source"),
    }


def build(
    rows: Iterable[dict[str, Any]],
    *,
    source_run: str,
    attempts_path: Path | None,
    limit: int,
    min_score: int,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    attempts = load_attempt_index(attempts_path) if attempts_path and attempts_path.exists() else {}
    selected: list[tuple[int, float, str, dict[str, Any]]] = []
    stats: Counter[str] = Counter()
    portals: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    seen: set[str] = set()

    for row in rows:
        stats["input_rows"] += 1
        cid = candidate_id(row)
        if not cid:
            stats["skip_missing_id"] += 1
            continue
        key = cid.casefold()
        if key in seen:
            stats["skip_duplicate_id"] += 1
            continue
        seen.add(key)

        reason = str(row.get("queue_reason") or row.get("change_type") or row.get("event") or "").upper()
        if reason not in {"NEW", "UPDATED"}:
            stats["skip_not_new_or_updated"] += 1
            continue

        n = flat_notice(row)
        if is_obvious_non_bid(n):
            stats["skip_obvious_non_bid"] += 1
            continue

        deadline = parse_deadline(row)
        if deadline is None:
            stats["skip_deadline_unknown"] += 1
            continue
        seconds_left = (deadline - current).total_seconds()
        if seconds_left <= 7200:
            stats["skip_expired_or_too_late"] += 1
            continue

        fit, fit_class, score, reasons = business_fit(n)
        if not fit or fit_class not in CORE_CLASSES or score < min_score:
            stats["skip_not_express_core"] += 1
            continue

        has_title_signal = "scope-signal:title" in reasons
        has_strong_code = any(r.startswith("signals:") and ("cpv:" in r or "naics:" in r) for r in reasons)
        if not (has_title_signal or has_strong_code):
            stats["skip_description_only"] += 1
            continue

        portal, _raw_portal = resolve_dce_portal(n)
        if portal not in SUPPORTED:
            stats["skip_unsupported_dce_portal"] += 1
            continue

        probe = attempt_probe(row, source_run)
        if attempts and was_attempted(probe, attempts):
            stats["skip_exact_version_attempted"] += 1
            continue

        hours_left = max(0.0, seconds_left / 3600.0)
        urgency_bonus = 8 if hours_left <= 72 else 5 if hours_left <= 168 else 2 if hours_left <= 336 else 0
        priority = min(100, score + urgency_bonus)
        out = {
            "schema": SCHEMA,
            "candidate_id": cid,
            "material_fields_hash": material_hash(row) or None,
            "preliminary_score": priority,
            "business_fit_score": score,
            "selection_fit_class": fit_class,
            "wide_read_run_id": str(source_run),
            "source_discovery_run": str(source_run),
            "status": "AUTO_DCE_PREFETCH",
            "selection_portal": portal_key(n),
            "resolved_dce_portal": portal,
            "selection_bucket": "fresh-digital-express",
            "selection_freshness": "material_new_or_updated",
            "deadline": deadline.isoformat(),
            "hours_to_deadline_at_selection": round(hours_left, 3),
            "selection_reason": "Fresh NEW/UPDATED direct-core express route to DCE only; DCE and final mandatory gates remain authoritative | " + " | ".join(reasons[:8]),
            "title": n.get("title"),
            "buyer": n.get("buyer"),
            "notice_url": n.get("notice_url") or n.get("url"),
        }
        out = {k: v for k, v in out.items() if v is not None}
        selected.append((priority, -hours_left, key, out))
        portals[portal] += 1
        classes[fit_class] += 1
        stats["eligible_before_limit"] += 1

    selected.sort(key=lambda x: (-x[0], x[1], x[2]))
    output = [x[3] for x in selected[: max(0, limit)]]
    stats["selected"] = len(output)
    stats["deferred_by_limit"] = max(0, len(selected) - len(output))
    summary = {
        "schema": SUMMARY_SCHEMA,
        "source_run": str(source_run),
        "min_score": int(min_score),
        "limit": int(limit),
        "counts": dict(sorted(stats.items())),
        "portal_counts": dict(sorted(portals.items())),
        "fit_class_counts": dict(sorted(classes.items())),
        "safety": {
            "new_or_updated_only": True,
            "obvious_non_bid_notices_excluded_from_express_only": True,
            "requires_parseable_live_deadline": True,
            "description_only_does_not_enter_express": True,
            "supported_dce_portal_required": True,
            "exact_version_attempt_ledger_checked": True,
            "express_lane_can_create_green": False,
            "authoritative_dce_required_downstream": True,
            "semantic_qwen_lane_remains_independent": True,
            "drops_or_deletes_notices": False,
        },
    }
    return output, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a bounded precision-biased NEW/UPDATED direct-core lane to DCE.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--source-run", required=True)
    ap.add_argument("--attempt-ledger", default="control/dce_attempt_ledger.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--limit", type=int, default=48)
    ap.add_argument("--min-score", type=int, default=84)
    args = ap.parse_args()
    rows, summary = build(
        iter_rows(Path(args.input)),
        source_run=str(args.source_run),
        attempts_path=Path(args.attempt_ledger) if args.attempt_ledger else None,
        limit=max(0, args.limit),
        min_score=max(0, min(100, args.min_score)),
    )
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")
    sp = Path(args.summary); sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
