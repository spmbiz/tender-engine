from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def clean(value):
    return " ".join(str(value or "").split())


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                yield value


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-months", required=True)
    args = parser.parse_args()

    expected = [x.strip() for x in args.expected_months.split(",") if x.strip()]
    errors = []
    shard_stats = []
    records = {}
    source_releases_seen = 0
    source_publications_unique_sum = 0

    for month in expected:
        shard_dir = args.root / f"month-{month}"
        stats_path = shard_dir / "stats.json"
        if not stats_path.exists():
            errors.append({"month": month, "type": "MISSING_STATS"})
            continue
        try:
            stats = read_json(stats_path)
        except Exception as exc:
            errors.append({"month": month, "type": "UNREADABLE_STATS", "error": repr(exc)})
            continue
        shard_stats.append(stats)
        if stats.get("month") != month:
            errors.append({"month": month, "type": "MONTH_IDENTITY_MISMATCH", "observed": stats.get("month")})
        if stats.get("listing_contract") != "DE_DOE_OFFICIAL_MONTHLY_OCDS_SHARD_V1":
            errors.append({"month": month, "type": "SHARD_CONTRACT_MISMATCH", "observed": stats.get("listing_contract")})
        if stats.get("enumeration_complete") is not True or stats.get("errors"):
            errors.append({"month": month, "type": "SHARD_INCOMPLETE", "errors": stats.get("errors") or []})
        source_releases_seen += int(stats.get("source_releases_seen") or 0)
        source_publications_unique_sum += int(stats.get("source_publications_unique") or 0)

        for row in iter_jsonl(shard_dir / "raw.jsonl"):
            cid = clean(row.get("candidate_id"))
            if not cid:
                errors.append({"month": month, "type": "CANDIDATE_ID_MISSING"})
                continue
            old = records.get(cid)
            if not old or clean(row.get("published")) >= clean(old.get("published")):
                records[cid] = row

    completed_months = sorted({clean(x.get("month")) for x in shard_stats if x.get("enumeration_complete") is True and not x.get("errors")})
    exact_month_manifest = completed_months == expected
    complete = bool(not errors and exact_month_manifest and len(shard_stats) == len(expected))

    raw = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x.get("candidate_id") or ""))
    current = [x for x in raw if x.get("current")]
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "raw.jsonl", raw)
    write_jsonl(args.output / "current.jsonl", current)
    stats = {
        "source": "DE_DOE",
        "portal": "DE_BEKANNTMACHUNGSSERVICE",
        "listing_contract": "DE_DOE_OFFICIAL_MONTHLY_OCDS_SHARDED_V2",
        "first_official_month": expected[0] if expected else None,
        "last_requested_month": expected[-1] if expected else None,
        "months_requested": len(expected),
        "months_completed": len(completed_months),
        "month_manifest": expected,
        "completed_months": completed_months,
        "source_releases_seen_sum": source_releases_seen,
        "source_publications_unique_sum": source_publications_unique_sum,
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "publication_window_enumeration_complete": complete,
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": complete and bool(current),
        "errors": errors,
        "shards": [
            {
                "month": x.get("month"),
                "source_releases_seen": x.get("source_releases_seen"),
                "raw_materialized": x.get("raw_materialized"),
                "current_materialized": x.get("current_materialized"),
                "enumeration_complete": x.get("enumeration_complete"),
            }
            for x in sorted(shard_stats, key=lambda y: clean(y.get("month")))
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": "Exact merge of every independently fetched official German Bekanntmachungsservice monthly OCDS partition from 2022-12 through the requested current month. Full live coverage credit requires every expected month to materialize under the shard contract with zero errors; candidate versions are reconciled across months by deterministic candidate_id and latest published timestamp.",
    }
    (args.output / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not complete or not raw:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
