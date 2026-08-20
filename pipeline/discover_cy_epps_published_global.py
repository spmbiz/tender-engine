from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE = "https://www.eprocurement.gov.cy"
LIST_URL = BASE + "/epps/notices/viewPublishedNotices.do"
UA = "Tender-Engine/7.5 (+official Cyprus ePPS national Published Notices; publisher-pager contract)"
PAGE_SIZE = 10
RETRIES = max(1, min(8, int(os.getenv("CY_EPPS_PUBLISHED_RETRIES", "5"))))
PAGE_DELAY = max(0.0, float(os.getenv("CY_EPPS_PUBLISHED_PAGE_DELAY_SECONDS", "0.12")))

BANNER_RE = re.compile(
    r"(?:Προβολή\s+των|Showing)\s*:\s*([\d,.]+)\s*[-–]\s*([\d,.]+).*?([\d,.]+)\s+(?:συνολικών\s+αποτελεσμάτων|total\s+results?)",
    re.I,
)
PAGE_SELECTION_RE = re.compile(r"writePageSelection\(\s*[\"']([\d,.]+)[\"']\s*,\s*[\"']\?([^\"']*-p=)[\"']", re.I)
COMPETITION_RE = re.compile(
    r"contract notice|corrigendum|prior information|pre-information|"
    r"προκήρυξη σύμβασης|διορθωτική προκήρυξη|προκήρυξη τροποποίησης|"
    r"γνωστοποίηση σύμβασης|προκήρυξη διαγωνισμού|"
    r"προκήρυξη|διαγωνισ",
    re.I,
)
AWARD_RE = re.compile(r"award notice|contract award|γνωστοποίηση συναφθείσας|ανάθεση", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\b")


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def integer(value: Any) -> int | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def page_url(page: int, pager_prefix: str | None = None) -> str:
    if page <= 1:
        return LIST_URL
    prefix = pager_prefix or "d-446978-p="
    return f"{LIST_URL}?{prefix}{page}"


def fetch(session: requests.Session, url: str) -> requests.Response:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = session.get(url, timeout=60, allow_redirects=True)
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            if attempt + 1 < RETRIES:
                time.sleep(min(15.0, 1.25 * (2**attempt)))
    raise RuntimeError(f"CY_EPPS_PUBLISHED_FETCH_FAILED {url}: {last!r}")


def parse_banner(soup: BeautifulSoup) -> tuple[int, int, int]:
    candidates = soup.select("div.Pagination6, .table-pagination, .pagebanner")
    texts = [clean(node.get_text(" ", strip=True)) for node in candidates]
    texts.append(clean(soup.get_text(" ", strip=True)))
    for text in texts:
        match = BANNER_RE.search(text)
        if match:
            start = integer(match.group(1))
            end = integer(match.group(2))
            total = integer(match.group(3))
            if start and end and total:
                return start, end, total
    raise RuntimeError("CY_EPPS_PUBLISHED_BANNER_NOT_PARSED")


def parse_pager_contract(soup: BeautifulSoup) -> dict[str, Any]:
    html = str(soup)
    match = PAGE_SELECTION_RE.search(html)
    if not match:
        raise RuntimeError("CY_EPPS_PUBLISHED_PAGE_SELECTION_CONTRACT_MISSING")
    total_pages = integer(match.group(1))
    prefix = clean(match.group(2))
    next_button = soup.find(id="nextNav")
    last_button = soup.find(id="lastNav")
    next_href = next_button.get("href") if next_button else None
    last_href = last_button.get("href") if last_button else None
    return {
        "total_pages": total_pages,
        "pager_prefix": prefix,
        "next_href": next_href,
        "last_href": last_href,
    }


def row_dates(text: str) -> list[str]:
    out = []
    for match in DATE_RE.finditer(text):
        raw = match.group(1) + ((" " + match.group(2)) if match.group(2) else "")
        out.append(raw)
    return out


def parse_notice_row(tr, page_no: int) -> dict[str, Any] | None:
    cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
    if not cells:
        return None
    links = []
    chosen = None
    for anchor in tr.find_all("a", href=True):
        absolute = urljoin(LIST_URL, anchor.get("href") or "")
        if "viewPublished" not in absolute:
            continue
        links.append(absolute)
        qs = parse_qs(urlsplit(absolute).query)
        if qs.get("noticeId") or qs.get("documentId") or qs.get("resourceId"):
            chosen = (absolute, qs)
            break
    if not chosen:
        return None
    absolute, qs = chosen
    notice_id = clean((qs.get("noticeId") or qs.get("extId") or [""])[0])
    document_id = clean((qs.get("documentId") or [""])[0])
    resource_id = clean((qs.get("resourceId") or [""])[0])
    notice_type_id = clean((qs.get("noticeType") or [""])[0])
    if not notice_id and not document_id:
        return None
    text = clean(tr.get_text(" ", strip=True))
    notice_type_text = cells[0] if cells else None
    title = cells[1] if len(cells) > 1 else text
    dates = row_dates(text)
    submission_date = dates[0] if dates else None
    publication_date = dates[-1] if len(dates) > 1 else None
    status = cells[-2] if len(cells) >= 2 else None
    language = cells[-3] if len(cells) >= 3 else None
    return {
        "notice_id": notice_id or None,
        "document_id": document_id or None,
        "resource_id": resource_id or None,
        "notice_type_id": notice_type_id or None,
        "notice_type": clean(notice_type_text) or None,
        "title": clean(title) or None,
        "published_notice_submission_date": submission_date,
        "published": publication_date,
        "status": clean(status) or None,
        "language": clean(language) or None,
        "notice_url": absolute,
        "competition_relevant": bool(COMPETITION_RE.search(text) and not AWARD_RE.search(text)),
        "row_text": text,
        "source_page": page_no,
    }


def parse_page(response: requests.Response, requested_page: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    soup = BeautifulSoup(response.text, "html.parser")
    start, end, total = parse_banner(soup)
    pager = parse_pager_contract(soup)
    expected_start = (requested_page - 1) * PAGE_SIZE + 1
    expected_end = min(requested_page * PAGE_SIZE, total)
    if start != expected_start or end != expected_end:
        raise RuntimeError(
            f"CY_EPPS_PUBLISHED_PAGE_RANGE_MISMATCH requested={requested_page} observed={start}-{end} expected={expected_start}-{expected_end} total={total}"
        )
    expected_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if pager.get("total_pages") != expected_pages:
        raise RuntimeError(
            f"CY_EPPS_PUBLISHED_PAGE_COUNT_MISMATCH banner_total={total} pager_pages={pager.get('total_pages')} expected_pages={expected_pages}"
        )
    rows = []
    for tr in soup.find_all("tr"):
        row = parse_notice_row(tr, requested_page)
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
        "total_pages": pager.get("total_pages"),
        "pager_prefix": pager.get("pager_prefix"),
        "next_href": pager.get("next_href"),
        "last_href": pager.get("last_href"),
        "rows": len(rows),
        "competition_rows": sum(1 for row in rows if row.get("competition_relevant")),
        "competition_rows_without_resource_id": sum(1 for row in rows if row.get("competition_relevant") and not row.get("resource_id")),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
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
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"})

    rows: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total: int | None = None
    total_pages: int | None = None
    pager_prefix: str | None = None

    for page in range(start_page, end_page + 1):
        try:
            response = fetch(session, page_url(page, pager_prefix))
            page_rows, proof = parse_page(response, page)
            if total is None:
                total = int(proof["total_reported"])
                total_pages = int(proof["total_pages"])
                pager_prefix = clean(proof.get("pager_prefix")) or None
            elif int(proof["total_reported"]) != total or int(proof["total_pages"]) != total_pages:
                raise RuntimeError(
                    f"CY_EPPS_PUBLISHED_TOTAL_DRIFT page={page} total={proof['total_reported']}/{total} pages={proof['total_pages']}/{total_pages}"
                )
            rows.extend(page_rows)
            telemetry.append(proof)
        except Exception as exc:
            errors.append({"page": page, "error": repr(exc)})
            break
        if PAGE_DELAY:
            time.sleep(PAGE_DELAY)

    expected_page_count = end_page - start_page + 1
    shard_complete = bool(not errors and len(telemetry) == expected_page_count)
    notice_ids = [row.get("notice_id") or row.get("document_id") for row in rows]
    unique_notice_ids = len(set(notice_ids))
    expected_rows = sum(int(item["range_end"]) - int(item["range_start"]) + 1 for item in telemetry)
    exact_row_reconciliation = bool(shard_complete and len(rows) == expected_rows and unique_notice_ids == len(rows))

    write_jsonl(out / "notices.jsonl", rows)
    stats = {
        "source": "CYPRUS_EPPS_PUBLISHED",
        "listing_contract": "CY_EPPS_NATIONAL_PUBLISHED_NOTICES_DISPLAYTAG_V1",
        "page_start": start_page,
        "page_end": end_page,
        "pages_requested": expected_page_count,
        "pages_completed": len(telemetry),
        "total_reported": total,
        "total_pages": total_pages,
        "publisher_pager_prefix": pager_prefix,
        "rows_materialized": len(rows),
        "unique_notice_ids": unique_notice_ids,
        "competition_rows": sum(1 for row in rows if row.get("competition_relevant")),
        "competition_rows_without_resource_id": sum(1 for row in rows if row.get("competition_relevant") and not row.get("resource_id")),
        "shard_complete": shard_complete,
        "exact_row_reconciliation": exact_row_reconciliation,
        "errors": errors,
        "telemetry": telemetry,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": (
            "Official Cyprus ePPS national Published Notices only, without authority/orgGroup filters. "
            "The DisplayTag page-number prefix and total-page count come from the publisher's own writePageSelection markup; page ranges and row counts are exact-reconciled against the visible publisher banner. "
            "This collector enumerates published notice identities only. It does not claim Current Opportunities coverage until competition resourceIds are independently resolved against public CfT workspaces."
        ),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not shard_complete or not exact_row_reconciliation:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
