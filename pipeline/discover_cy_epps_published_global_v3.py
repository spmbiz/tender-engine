from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from pipeline import discover_cy_epps_published_global_v2 as _v2  # noqa: F401
    from pipeline import discover_cy_epps_published_global as base
except ModuleNotFoundError:
    import discover_cy_epps_published_global_v2 as _v2  # noqa: F401
    import discover_cy_epps_published_global as base


def publication_identity(row: dict[str, Any]) -> str:
    notice_id = base.clean(row.get("notice_id"))
    document_id = base.clean(row.get("document_id"))
    if notice_id and document_id:
        return f"{notice_id}:{document_id}"
    if document_id:
        return f"DOC:{document_id}"
    if notice_id:
        return f"NOTICE:{notice_id}"
    url = base.clean(row.get("notice_url"))
    if url:
        return f"URL:{url}"
    return ""


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/CYPRUS_EPPS_PUBLISHED")))
    parser.add_argument("--page-start", type=int, default=int(os.getenv("CY_PAGE_START", "1")))
    parser.add_argument("--page-end", type=int, default=int(os.getenv("CY_PAGE_END", "3")))
    args = parser.parse_args()

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    start_page = max(1, args.page_start)
    end_page = max(start_page, args.page_end)
    session = base.requests.Session()
    session.headers.update({"User-Agent": base.UA, "Accept": "text/html,application/xhtml+xml,*/*"})

    rows: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = None
    total_pages = None
    pager_prefix = None

    for page in range(start_page, end_page + 1):
        try:
            response = base.fetch(session, base.page_url(page, pager_prefix))
            page_rows, proof = base.parse_page(response, page)
            if total is None:
                total = int(proof["total_reported"])
                total_pages = int(proof["total_pages"])
                pager_prefix = base.clean(proof.get("pager_prefix")) or None
            elif int(proof["total_reported"]) != total or int(proof["total_pages"]) != total_pages:
                raise RuntimeError(
                    f"CY_EPPS_PUBLISHED_TOTAL_DRIFT page={page} total={proof['total_reported']}/{total} pages={proof['total_pages']}/{total_pages}"
                )
            rows.extend(page_rows)
            telemetry.append(proof)
        except Exception as exc:
            errors.append({"page": page, "error": repr(exc)})
            break
        if base.PAGE_DELAY:
            time.sleep(base.PAGE_DELAY)

    expected_page_count = end_page - start_page + 1
    shard_complete = bool(not errors and len(telemetry) == expected_page_count)
    publication_ids = [publication_identity(row) for row in rows]
    missing_publication_identity = sum(1 for value in publication_ids if not value)
    unique_publication_ids = len({value for value in publication_ids if value})
    notice_ids = {base.clean(row.get("notice_id")) for row in rows if base.clean(row.get("notice_id"))}
    resource_ids = {base.clean(row.get("resource_id")) for row in rows if base.clean(row.get("resource_id"))}
    competition_resource_ids = {
        base.clean(row.get("resource_id"))
        for row in rows
        if row.get("competition_relevant") and base.clean(row.get("resource_id"))
    }
    expected_rows = sum(int(item["range_end"]) - int(item["range_start"]) + 1 for item in telemetry)
    exact_row_reconciliation = bool(
        shard_complete
        and len(rows) == expected_rows
        and missing_publication_identity == 0
        and unique_publication_ids == len(rows)
    )

    for row in rows:
        row["publication_id"] = publication_identity(row)
        row["grain"] = "PUBLISHED_NOTICE_DOCUMENT"
    write_jsonl(out / "notices.jsonl", rows)
    stats = {
        "source": "CYPRUS_EPPS_PUBLISHED",
        "listing_contract": "CY_EPPS_NATIONAL_PUBLISHED_NOTICES_DISPLAYTAG_V3_PUBLICATION_GRAIN",
        "page_start": start_page,
        "page_end": end_page,
        "pages_requested": expected_page_count,
        "pages_completed": len(telemetry),
        "total_reported": total,
        "total_pages": total_pages,
        "publisher_pager_prefix": pager_prefix,
        "rows_materialized": len(rows),
        "unique_publication_ids": unique_publication_ids,
        "unique_notice_ids": len(notice_ids),
        "unique_resource_ids": len(resource_ids),
        "unique_competition_resource_ids": len(competition_resource_ids),
        "missing_publication_identity": missing_publication_identity,
        "competition_rows": sum(1 for row in rows if row.get("competition_relevant")),
        "competition_rows_without_resource_id": sum(1 for row in rows if row.get("competition_relevant") and not row.get("resource_id")),
        "shard_complete": shard_complete,
        "exact_row_reconciliation": exact_row_reconciliation,
        "errors": errors,
        "telemetry": telemetry,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": (
            "Official Cyprus ePPS national Published Notices at publication-document grain. Multiple publications may legitimately belong to the same notice or CfT resource. "
            "Exact registry reconciliation therefore uses noticeId+documentId (with deterministic single-field/URL fallbacks), while resourceId is a later procedure/workspace linkage key. "
            "Page ranges and official totals remain exact-reconciled; Current Opportunities coverage is not claimed until all unique competition resourceIds are resolved through public CfT workspaces."
        ),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not shard_complete or not exact_row_reconciliation:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
