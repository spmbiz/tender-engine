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
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--expected-resources", type=int, required=True)
    args = ap.parse_args()

    stats_files = sorted(args.root.rglob("stats.json"))
    errors = []
    intervals = []
    rows_by_resource = {}
    unknown_by_resource = {}
    transport_complete_all = True

    for stats_path in stats_files:
        try:
            stats = read_json(stats_path)
        except Exception as exc:
            errors.append({"type": "UNREADABLE_STATS", "path": str(stats_path), "error": repr(exc)})
            continue
        if stats.get("listing_contract") != "CY_EPPS_PUBLIC_CFT_WORKSPACE_RESOLVER_V1":
            errors.append({"type": "SHARD_CONTRACT_MISMATCH", "path": str(stats_path), "observed": stats.get("listing_contract")})
        start = int(stats.get("start_index") or 0)
        end = int(stats.get("end_index_exclusive") or 0)
        if start < 0 or end < start:
            errors.append({"type": "INVALID_INDEX_RANGE", "path": str(stats_path), "start": start, "end": end})
        intervals.append((start, end, str(stats_path)))
        if stats.get("transport_complete") is not True or stats.get("errors"):
            transport_complete_all = False
            errors.append({"type": "SHARD_TRANSPORT_INCOMPLETE", "path": str(stats_path), "errors": stats.get("errors") or []})

        resolved = list(iter_jsonl(stats_path.parent / "resolved.jsonl"))
        if len(resolved) != int(stats.get("resources_resolved") or -1):
            errors.append({"type": "RESOLVED_FILE_COUNT_MISMATCH", "path": str(stats_path), "file_rows": len(resolved), "stats_rows": stats.get("resources_resolved")})
        for row in resolved:
            rid = clean(row.get("resource_id"))
            if not rid:
                errors.append({"type": "RESOURCE_ID_MISSING", "path": str(stats_path)})
                continue
            if rid in rows_by_resource:
                errors.append({"type": "DUPLICATE_RESOURCE_ACROSS_SHARDS", "resource_id": rid})
                continue
            rows_by_resource[rid] = row
            if row.get("current_state") == "UNKNOWN":
                unknown_by_resource[rid] = row

    index_owner = {}
    for start, end, path in intervals:
        for index in range(start, end):
            if index in index_owner:
                errors.append({"type": "INDEX_OVERLAP", "index": index, "first": index_owner[index], "second": path})
            index_owner[index] = path
    expected_indices = set(range(args.expected_resources))
    observed_indices = set(index_owner)
    missing = sorted(expected_indices - observed_indices)
    extra = sorted(observed_indices - expected_indices)
    if missing:
        errors.append({"type": "MISSING_RESOURCE_INDEXES", "count": len(missing), "sample": missing[:50]})
    if extra:
        errors.append({"type": "EXTRA_RESOURCE_INDEXES", "count": len(extra), "sample": extra[:50]})

    exact_transport_reconciliation = bool(
        not errors
        and transport_complete_all
        and observed_indices == expected_indices
        and len(rows_by_resource) == args.expected_resources
    )
    currentness_complete = bool(exact_transport_reconciliation and not unknown_by_resource)

    rows = sorted(rows_by_resource.values(), key=lambda x: clean(x.get("resource_id")))
    current = [row for row in rows if row.get("current") is True]
    non_current = [row for row in rows if row.get("current_state") == "NON_CURRENT"]
    unknown = [row for row in rows if row.get("current_state") == "UNKNOWN"]
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "resolved.jsonl", rows)
    write_jsonl(args.output / "current.jsonl", current)
    write_jsonl(args.output / "non_current.jsonl", non_current)
    write_jsonl(args.output / "unknown.jsonl", unknown)
    stats = {
        "source": "CYPRUS_EPPS",
        "listing_contract": "CY_EPPS_PUBLIC_CFT_WORKSPACE_SHARDED_V2",
        "expected_resources": args.expected_resources,
        "resources_resolved": len(rows),
        "current_materialized": len(current),
        "non_current_materialized": len(non_current),
        "unknown_currentness": len(unknown),
        "index_manifest_complete": observed_indices == expected_indices,
        "exact_transport_reconciliation": exact_transport_reconciliation,
        "currentness_complete": currentness_complete,
        "enumeration_exhausted": exact_transport_reconciliation,
        "enumeration_complete": currentness_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": currentness_complete and bool(current),
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": (
            "Exact merge of all public Cyprus ePPS CfT workspace resource shards generated from the fully reconciled national Published Notices registry. "
            "Transport completeness requires every deduplicated competition resource index exactly once and every public workspace fetched successfully. "
            "Live coverage additionally requires zero UNKNOWN currentness classifications: explicit future deadline is CURRENT, expired deadline or terminal evidence is NON_CURRENT, and missing both remains UNKNOWN/fail-closed."
        ),
    }
    (args.output / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not exact_transport_reconciliation:
        raise SystemExit(3)
    if not currentness_complete:
        raise SystemExit(4)


if __name__ == "__main__":
    main()
