from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

try:
    from pipeline import discover_cy_epps_published_global as base
except ModuleNotFoundError:
    import discover_cy_epps_published_global as base

_ORIGINAL_PARSE_PAGER = base.parse_pager_contract
PAGE_HREF_RE = re.compile(r"[?&]([^?&=]*-p=)(\d+)", re.I)


def relaxed_pager(soup: BeautifulSoup, expected_pages: int) -> dict[str, Any]:
    try:
        return _ORIGINAL_PARSE_PAGER(soup)
    except Exception:
        pass

    next_button = soup.find(id="nextNav")
    last_button = soup.find(id="lastNav")
    first_button = soup.find(id="firstNav")
    next_href = next_button.get("href") if next_button else None
    last_href = last_button.get("href") if last_button else None
    prefix = None
    observed_last = None
    for href in (last_href, next_href, first_button.get("href") if first_button else None):
        if not href:
            continue
        match = PAGE_HREF_RE.search(href)
        if match:
            prefix = match.group(1)
            if href == last_href:
                try:
                    observed_last = int(match.group(2))
                except Exception:
                    observed_last = None
            break
    if observed_last is not None and observed_last != expected_pages:
        raise RuntimeError(
            f"CY_EPPS_PUBLISHED_LAST_PAGE_MISMATCH observed={observed_last} expected={expected_pages}"
        )
    return {
        "total_pages": expected_pages,
        "pager_prefix": prefix,
        "next_href": next_href,
        "last_href": last_href,
        "metadata_source": "BANNER_TOTAL_PLUS_PUBLISHER_NAV_HREFS",
    }


def parse_page(response, requested_page: int):
    soup = BeautifulSoup(response.text, "html.parser")
    start, end, total = base.parse_banner(soup)
    expected_start = (requested_page - 1) * base.PAGE_SIZE + 1
    expected_end = min(requested_page * base.PAGE_SIZE, total)
    if start != expected_start or end != expected_end:
        raise RuntimeError(
            f"CY_EPPS_PUBLISHED_PAGE_RANGE_MISMATCH requested={requested_page} observed={start}-{end} expected={expected_start}-{expected_end} total={total}"
        )
    expected_pages = (total + base.PAGE_SIZE - 1) // base.PAGE_SIZE
    pager = relaxed_pager(soup, expected_pages)

    rows = []
    for tr in soup.find_all("tr"):
        row = base.parse_notice_row(tr, requested_page)
        if row:
            rows.append(row)
    expected_rows = expected_end - expected_start + 1
    if len(rows) != expected_rows:
        raise RuntimeError(
            f"CY_EPPS_PUBLISHED_ROW_COUNT_MISMATCH page={requested_page} rows={len(rows)} expected={expected_rows} total={total}"
        )
    ids = [row.get("notice_id") or row.get("document_id") for row in rows]
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"CY_EPPS_PUBLISHED_DUPLICATE_NOTICE_ID_WITHIN_PAGE page={requested_page}")

    return rows, {
        "page": requested_page,
        "range_start": start,
        "range_end": end,
        "total_reported": total,
        "total_pages": expected_pages,
        "pager_prefix": pager.get("pager_prefix"),
        "next_href": pager.get("next_href"),
        "last_href": pager.get("last_href"),
        "pager_metadata_source": pager.get("metadata_source") or "WRITE_PAGE_SELECTION",
        "rows": len(rows),
        "competition_rows": sum(1 for row in rows if row.get("competition_relevant")),
        "competition_rows_without_resource_id": sum(1 for row in rows if row.get("competition_relevant") and not row.get("resource_id")),
    }


base.parse_page = parse_page


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
