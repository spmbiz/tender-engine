from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"INVALID_JSONL {path}:{line_no}: {exc!r}") from exc
            if isinstance(row, dict):
                yield row


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def candidate_key(row: dict) -> str | None:
    cid = str(row.get("candidate_id") or "").strip()
    if cid:
        return cid
    pub = str(row.get("publication_number") or "").strip()
    return f"TED:{pub}" if pub else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--expected-years", required=True, help="Comma-separated years, e.g. 2016,2017,2018")
    args = ap.parse_args()

    years = [int(x) for x in args.expected_years.split(",") if x.strip()]
    years = sorted(set(years))
    if not years:
        raise SystemExit("NO_EXPECTED_YEARS")

    records: dict[str, dict] = {}
    shard_stats = []
    errors = []
    complete_years = []
    total_reported_sum = 0
    source_items_seen_sum = 0
    retry_events_sum = 0

    for year in years:
        shard = args.root / f"year-{year}"
        stats_path = shard / "stats.json"
        active_path = shard / "active.jsonl"
        stats = read_json(stats_path)
        if not isinstance(stats, dict):
            errors.append({"year": year, "type": "TED_YEAR_SHARD_STATS_MISSING_OR_INVALID", "path": str(stats_path)})
            continue
        shard_stats.append({
            "year": year,
            "query": stats.get("query"),
            "pages": stats.get("pages"),
            "total_reported": stats.get("total_reported"),
            "source_items_seen": stats.get("source_items_seen"),
            "materialized_unique": stats.get("materialized_unique"),
            "current_materialized": stats.get("current_materialized"),
            "enumeration_complete": stats.get("enumeration_complete"),
            "errors": stats.get("errors") or [],
            "rate_limit_events": stats.get("rate_limit_events"),
            "malformed_json_retry_events": stats.get("malformed_json_retry_events"),
        })
        if stats.get("enumeration_complete") is not True or stats.get("errors"):
            errors.append({
                "year": year,
                "type": "TED_YEAR_SHARD_INCOMPLETE",
                "stats_errors": stats.get("errors") or [],
                "pages": stats.get("pages"),
                "total_reported": stats.get("total_reported"),
                "source_items_seen": stats.get("source_items_seen"),
            })
            continue
        if not active_path.exists():
            errors.append({"year": year, "type": "TED_YEAR_SHARD_ACTIVE_JSONL_MISSING", "path": str(active_path)})
            continue

        complete_years.append(year)
        try:
            total_reported_sum += int(stats.get("total_reported") or 0)
            source_items_seen_sum += int(stats.get("source_items_seen") or 0)
            retry_events_sum += len(stats.get("retry_events") or [])
        except Exception:
            pass

        for row in iter_jsonl(active_path):
            key = candidate_key(row)
            if not key:
                errors.append({"year": year, "type": "TED_ROW_ID_MISSING"})
                continue
            previous = records.get(key)
            if previous is None:
                records[key] = row
            elif previous != row:
                # Non-destructive exact-ID collision handling: preserve the first
                # canonical row and surface the collision instead of fuzzy-merging.
                errors.append({"year": year, "type": "TED_EXACT_ID_CONTENT_COLLISION", "candidate_id": key})

    rows = sorted(records.values(), key=lambda r: (str(r.get("publication_date") or ""), str(r.get("candidate_id") or "")))
    current = [r for r in rows if r.get("current") is True]
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "active.jsonl", rows)
    write_jsonl(args.output / "current.jsonl", current)

    all_complete = len(complete_years) == len(years) and not errors
    stats = {
        "source": "TED",
        "scope": "ACTIVE",
        "enumeration_mode": "YEAR_SHARDED_ACTIVE_COMPETITION",
        "listing_contract": "TED_ACTIVE_YEAR_SHARDS_V1_EXACT_MERGE",
        "expected_years": years,
        "complete_years": complete_years,
        "shard_count_expected": len(years),
        "shard_count_complete": len(complete_years),
        "total_reported": total_reported_sum,
        "source_items_seen": source_items_seen_sum,
        "materialized_unique": len(rows),
        "current_materialized": len(current),
        "open_confirmed_by_future_deadline": sum(1 for r in current if r.get("currentness_evidence") == "PARSED_FUTURE_DEADLINE"),
        "open_unverified_no_parseable_deadline": sum(1 for r in current if r.get("currentness_evidence") == "NO_PARSEABLE_DEADLINE"),
        "retry_events_total": retry_events_sum,
        "enumeration_exhausted": all_complete,
        "enumeration_complete": all_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": all_complete and bool(current),
        "errors": errors,
        "shards": shard_stats,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": "TED ACTIVE competition notices are independently enumerated in non-overlapping publication-year shards using the official Search API ITERATION mode. Each shard must prove token exhaustion and reported-count coverage. Merge is exact by authoritative TED candidate/publication identity; any content collision is surfaced, never fuzzily reconciled. Currentness remains deadline-evidence aware and no notice-only FINAL_SUPER_GREEN claim is made.",
    }
    (args.output / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not all_complete:
        raise SystemExit(3)
    if not current:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
