#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

LEDGER_SCHEMA = "NOTICE_INTELLIGENCE_LEDGER_V1"
CHANGE_QUEUE_SCHEMA = "NOTICE_CHANGE_QUEUE_V1"

# These fields change the commercial/procurement meaning of a notice and must
# cause semantic reclassification. Derived runtime state (for example
# open_state) is intentionally excluded.
MATERIAL_FIELDS = (
    "source_family",
    "source",
    "country",
    "buyer",
    "title",
    "description",
    "cpv_or_category",
    "estimated_value",
    "currency",
    "publication_date",
    "deadline",
    "deadline_utc",
    "procedure",
    "lots",
    "notice_eligibility",
    "award_criteria",
    "subcontracting",
    "urls",
)

CLASSIFIER_FIELDS = (
    "classifier_model",
    "classifier_quant",
    "classifier_prompt_version",
    "classifier_version",
    "classification",
    "confidence",
    "novelty_or_unusual_flag",
    "classified_at",
    "review_status",
    "dce_status",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_text(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def read_jsonl(path: Path | None) -> Iterable[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return []
    rows: list[dict[str, Any]] = []
    with _open_text(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): stable_value(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [stable_value(v) for v in value]
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def digest(payload: Any) -> str:
    raw = json.dumps(stable_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def material_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in MATERIAL_FIELDS}


def notice_payload(row: dict[str, Any]) -> dict[str, Any]:
    # Hash the normalized snapshot row as supplied, while excluding transient
    # ledger annotations if a caller reuses a ledger-enriched row.
    return {k: v for k, v in row.items() if not str(k).startswith("ledger_")}


def canonical_url(row: dict[str, Any]) -> str | None:
    urls = row.get("urls")
    if isinstance(urls, str) and urls.strip():
        return urls.strip()
    if isinstance(urls, list):
        for value in urls:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for key in ("url", "href", "notice", "canonical"):
                    value2 = value.get(key)
                    if isinstance(value2, str) and value2.strip():
                        return value2.strip()
    return None


def source_notice_id(candidate_id: str) -> str:
    if ":" in candidate_id:
        return candidate_id.split(":", 1)[1]
    return candidate_id


def classifier_stale(previous: dict[str, Any], target_version: str | None) -> bool:
    if not previous.get("classification"):
        return True
    if target_version and str(previous.get("classifier_version") or "") != target_version:
        return True
    return False


def build(
    current_rows: Iterable[dict[str, Any]],
    previous_rows: Iterable[dict[str, Any]],
    *,
    now: str,
    target_classifier_version: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    previous: dict[str, dict[str, Any]] = {}
    for row in previous_rows:
        cid = str(row.get("canonical_notice_id") or row.get("candidate_id") or "").strip()
        if cid:
            previous[cid] = row

    previous_sources: Counter[str] = Counter(str(row.get("source") or "UNKNOWN") for row in previous.values())

    ledger: list[dict[str, Any]] = []
    change_queue: list[dict[str, Any]] = []
    classification_queue: list[dict[str, Any]] = []
    events: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    seen: set[str] = set()

    for row in current_rows:
        cid = str(row.get("candidate_id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        old = previous.get(cid)
        material_hash = digest(material_payload(row))
        full_hash = digest(notice_payload(row))

        if old is None:
            event = "NEW"
            first_seen = now
            previous_material_hash = None
        elif str(old.get("material_fields_hash") or "") != material_hash:
            event = "UPDATED"
            first_seen = str(old.get("first_seen_at") or now)
            previous_material_hash = old.get("material_fields_hash")
        else:
            event = "UNCHANGED"
            first_seen = str(old.get("first_seen_at") or now)
            previous_material_hash = old.get("previous_material_fields_hash")

        entry: dict[str, Any] = {
            "schema": LEDGER_SCHEMA,
            "source": row.get("source"),
            "source_notice_id": source_notice_id(cid),
            "canonical_notice_id": cid,
            "canonical_url": canonical_url(row),
            "first_seen_at": first_seen,
            "last_seen_at": now,
            "publication_date": row.get("publication_date"),
            "deadline": row.get("deadline"),
            "notice_hash": full_hash,
            "material_fields_hash": material_hash,
            "previous_material_fields_hash": previous_material_hash,
            "ledger_event": event,
        }
        for field in CLASSIFIER_FIELDS:
            entry[field] = old.get(field) if old else None

        needs = event in {"NEW", "UPDATED"} or classifier_stale(old or {}, target_classifier_version)
        entry["needs_reclassification"] = bool(needs)
        entry["classification_stale"] = bool(event == "UPDATED" and old and old.get("classification"))
        ledger.append(entry)
        events[event] += 1
        sources[str(row.get("source") or "UNKNOWN")] += 1

        queue_envelope = {
            "schema": CHANGE_QUEUE_SCHEMA,
            "queue_reason": event if event in {"NEW", "UPDATED"} else "CLASSIFIER_VERSION_OR_UNCLASSIFIED",
            "canonical_notice_id": cid,
            "material_fields_hash": material_hash,
            "previous_material_fields_hash": previous_material_hash,
            "first_seen_at": first_seen,
            "last_seen_at": now,
            "notice": row,
        }
        if event in {"NEW", "UPDATED"}:
            change_queue.append(queue_envelope)
        if needs:
            classification_queue.append(queue_envelope)

    dropped = sorted(set(previous) - seen)
    previous_count = len(previous)
    current_count = len(ledger)
    total_ratio = (current_count / previous_count) if previous_count else 1.0
    source_regressions = {}
    for source, prior_count in previous_sources.items():
        now_count = int(sources.get(source, 0))
        if prior_count >= 500 and now_count < prior_count * 0.50:
            source_regressions[source] = {
                "previous": prior_count,
                "current": now_count,
                "ratio": (now_count / prior_count) if prior_count else 0.0,
            }
    hard_fail = bool(
        (previous_count >= 1000 and total_ratio < 0.80)
        or source_regressions
    )
    summary = {
        "schema": "NOTICE_INTELLIGENCE_LEDGER_SUMMARY_V1",
        "generated_at": now,
        "current_unique": len(ledger),
        "previous_unique": len(previous),
        "new": events["NEW"],
        "updated": events["UPDATED"],
        "unchanged": events["UNCHANGED"],
        "dropped_since_previous": len(dropped),
        "change_queue": len(change_queue),
        "classification_queue": len(classification_queue),
        "target_classifier_version": target_classifier_version,
        "sources": dict(sorted(sources.items())),
        "generation_qualification": {
            "status": "REJECT_REGRESSION" if hard_fail else "PASS",
            "hard_fail": hard_fail,
            "current_vs_previous_ratio": total_ratio,
            "minimum_total_ratio": 0.80,
            "major_source_min_previous": 500,
            "major_source_min_ratio": 0.50,
            "source_regressions": source_regressions,
            "rule": "Never advance the stable ledger on catastrophic whole-universe loss or a >50% collapse of a previously large source. Snapshot carry-forward should normally prevent these conditions; hitting this guard requires investigation or an explicit code change, never silent acceptance.",
        },
        "rules": {
            "identity": "Exact canonical_notice_id only; no fuzzy cross-source merge.",
            "change_queue": "Only NEW or materially UPDATED notices enter the live change queue.",
            "classification_queue": "NEW/UPDATED plus notices missing the requested classifier version. This is shadow-only until Qwen rollout is measured.",
            "recall": "No ledger event deletes a tender or establishes eligibility/DCE truth.",
        },
    }
    return ledger, change_queue, classification_queue, summary


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _open_text(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/update the durable live Notice Intelligence Ledger.")
    ap.add_argument("--current", required=True, help="Normalized live_open_tenders JSONL(.gz)")
    ap.add_argument("--previous", help="Previous ledger JSONL(.gz); omitted on first backfill")
    ap.add_argument("--ledger-out", required=True)
    ap.add_argument("--change-queue-out", required=True)
    ap.add_argument("--classification-queue-out", required=True)
    ap.add_argument("--summary-out", required=True)
    ap.add_argument("--classifier-version", default="qwen-shadow-v1")
    ap.add_argument("--now", help="Deterministic ISO timestamp for tests")
    args = ap.parse_args()

    now = args.now or utc_now()
    ledger, changes, classification, summary = build(
        read_jsonl(Path(args.current)),
        read_jsonl(Path(args.previous)) if args.previous else [],
        now=now,
        target_classifier_version=args.classifier_version or None,
    )
    qualification = summary.get("generation_qualification") or {}
    if qualification.get("hard_fail"):
        Path(args.summary_out).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        raise SystemExit("Refusing to advance ledger: snapshot generation regressed below durable safety thresholds")

    write_jsonl(Path(args.ledger_out), ledger)
    write_jsonl(Path(args.change_queue_out), changes)
    write_jsonl(Path(args.classification_queue_out), classification)
    Path(args.summary_out).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
