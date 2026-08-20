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
    ap.add_argument("--total-pages", type=int, required=True)
    ap.add_argument("--total-reported", type=int, required=True)
    args = ap.parse_args()

    errors = []
    stats_files = sorted(args.root.rglob("stats.json"))
    shard_stats = []
    page_owners = {}
    publication_rows = {}
    row_count_sum = 0
    stable_totals = True

    for stats_path in stats_files:
        try:
            stats = read_json(stats_path)
        except Exception as exc:
            errors.append({"type": "UNREADABLE_STATS", "path": str(stats_path), "error": repr(exc)})
            continue
        shard_stats.append(stats)
        if stats.get("listing_contract") != "CY_EPPS_NATIONAL_PUBLISHED_NOTICES_DISPLAYTAG_V3_PUBLICATION_GRAIN":
            errors.append({"type": "SHARD_CONTRACT_MISMATCH", "path": str(stats_path), "observed": stats.get("listing_contract")})
        if stats.get("shard_complete") is not True or stats.get("exact_row_reconciliation") is not True or stats.get("errors"):
            errors.append({"type": "SHARD_INCOMPLETE", "path": str(stats_path), "errors": stats.get("errors") or []})
        if int(stats.get("total_pages") or -1) != args.total_pages or int(stats.get("total_reported") or -1) != args.total_reported:
            stable_totals = False
            errors.append({
                "type": "OFFICIAL_TOTAL_DRIFT",
                "path": str(stats_path),
                "observed_pages": stats.get("total_pages"),
                "expected_pages": args.total_pages,
                "observed_total": stats.get("total_reported"),
                "expected_total": args.total_reported,
            })
        start = int(stats.get("page_start") or 0)
        end = int(stats.get("page_end") or 0)
        if start < 1 or end < start:
            errors.append({"type": "INVALID_SHARD_RANGE", "path": str(stats_path), "start": start, "end": end})
            continue
        for page in range(start, end + 1):
            if page in page_owners:
                errors.append({"type": "PAGE_OVERLAP", "page": page, "first": page_owners[page], "second": str(stats_path)})
            page_owners[page] = str(stats_path)

        notices_path = stats_path.parent / "notices.jsonl"
        shard_rows = list(iter_jsonl(notices_path))
        row_count_sum += len(shard_rows)
        if len(shard_rows) != int(stats.get("rows_materialized") or -1):
            errors.append({"type": "SHARD_FILE_ROW_COUNT_MISMATCH", "path": str(notices_path), "file_rows": len(shard_rows), "stats_rows": stats.get("rows_materialized")})
        for row in shard_rows:
            publication_id = clean(row.get("publication_id"))
            if not publication_id:
                errors.append({"type": "PUBLICATION_ID_MISSING", "path": str(notices_path)})
                continue
            if publication_id in publication_rows:
                errors.append({"type": "DUPLICATE_PUBLICATION_ACROSS_SHARDS", "publication_id": publication_id})
                continue
            publication_rows[publication_id] = row

    expected_pages = set(range(1, args.total_pages + 1))
    observed_pages = set(page_owners)
    missing_pages = sorted(expected_pages - observed_pages)
    extra_pages = sorted(observed_pages - expected_pages)
    if missing_pages:
        errors.append({"type": "MISSING_PAGES", "count": len(missing_pages), "sample": missing_pages[:50]})
    if extra_pages:
        errors.append({"type": "EXTRA_PAGES", "count": len(extra_pages), "sample": extra_pages[:50]})

    exact_registry_reconciliation = bool(
        not errors
        and stable_totals
        and observed_pages == expected_pages
        and row_count_sum == args.total_reported
        and len(publication_rows) == args.total_reported
    )

    rows = sorted(publication_rows.values(), key=lambda x: (int(x.get("source_page") or 0), clean(x.get("publication_id"))))
    competition_resources = {}
    for row in rows:
        if not row.get("competition_relevant"):
            continue
        resource_id = clean(row.get("resource_id"))
        if not resource_id:
            continue
        old = competition_resources.get(resource_id)
        # Published registry is newest-first within the current sort. Preserve the
        # first seen publication as representative metadata for the procedure.
        if old is None:
            competition_resources[resource_id] = {
                "resource_id": resource_id,
                "title": row.get("title"),
                "notice_id": row.get("notice_id"),
                "document_id": row.get("document_id"),
                "notice_type": row.get("notice_type"),
                "notice_url": row.get("notice_url"),
                "source_page": row.get("source_page"),
                "publication_count": 1,
            }
        else:
            old["publication_count"] = int(old.get("publication_count") or 0) + 1

    resource_rows = sorted(competition_resources.values(), key=lambda x: x["resource_id"])
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "published_notices.jsonl", rows)
    write_jsonl(args.output / "competition_resources.jsonl", resource_rows)
    stats = {
        "source": "CYPRUS_EPPS_PUBLISHED",
        "listing_contract": "CY_EPPS_NATIONAL_PUBLISHED_NOTICES_SHARDED_V4_FULL_REGISTRY",
        "shards_materialized": len(shard_stats),
        "total_pages_official": args.total_pages,
        "total_pages_covered": len(observed_pages & expected_pages),
        "total_reported_official": args.total_reported,
        "rows_materialized": len(rows),
        "unique_publication_ids": len(publication_rows),
        "unique_competition_resource_ids": len(resource_rows),
        "stable_official_totals": stable_totals,
        "page_manifest_complete": observed_pages == expected_pages,
        "exact_registry_reconciliation": exact_registry_reconciliation,
        "enumeration_exhausted": exact_registry_reconciliation,
        "enumeration_complete": exact_registry_reconciliation,
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": (
            "Exact merge of all publisher-numbered pages of the Cyprus ePPS national Published Notices registry. "
            "Coverage requires every official page exactly once, stable total/pages across shards, total materialized publication-document rows equal to the publisher total, and globally unique publication IDs. "
            "Competition resourceIds are deduplicated only after full registry reconciliation and are inputs to the independent public CfT workspace currentness stage; this registry proof alone does not claim live Current Opportunities coverage."
        ),
    }
    (args.output / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not exact_registry_reconciliation:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
