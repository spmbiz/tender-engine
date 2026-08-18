from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UNGM_PUBLIC"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://www.ungm.org"
LIST_URL = BASE + "/Public/Notice"
SEARCH_URL = BASE + "/Public/Notice/Search"
NOW = datetime.now(timezone.utc)
PAGE_SIZE = 15
MAX_PAGES = max(1, int(os.getenv("UNGM_MAX_PAGES", "2000")))
REQUEST_RETRIES = max(1, int(os.getenv("UNGM_REQUEST_RETRIES", "5")))
PAGE_DELAY_SECONDS = max(0.0, float(os.getenv("UNGM_PAGE_DELAY_SECONDS", "0.08")))
NOTICE_RE = re.compile(r"/Public/Notice/(\d+)(?:\b|/|\?)", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}-[A-Za-z]{3}-20\d{2}|\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})\b")
TOTAL_RE = re.compile(r"(?:Displaying\s+results\s+\d+\s+to\s+\d+\s+of|noticeSearchTotal[^\d]{0,30})([\d,]+)", re.I)
UA = "Tender-Engine/6.8 (+public procurement research; UNGM public notice search)"


def clean(value):
    return " ".join(str(value or "").split())


def parse_date(value):
    text = clean(value)
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    m = DATE_RE.search(text)
    if m and m.group(1) != text:
        return parse_date(m.group(1))
    return None


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def payload(page_index: int) -> dict:
    # This is the same public JSON contract used by the UNGM Procurement
    # Opportunities grid. DeadlineFrom=today reproduces the site's active/open
    # semantics without requiring a login or the authenticated Notice API.
    return {
        "PageIndex": page_index,
        "PageSize": PAGE_SIZE,
        "Title": "",
        "Description": "",
        "Reference": "",
        "PublishedFrom": "",
        "PublishedTo": "",
        "DeadlineFrom": NOW.strftime("%d-%b-%Y"),
        "DeadlineTo": "",
        "Countries": [],
        "Agencies": [],
        "UNSPSCs": [],
        "NoticeTypes": [],
        "SortField": "DatePublished",
        "SortAscending": False,
        "isPicker": False,
        "NoticeTASStatus": [],
        "IsSustainable": False,
        "NoticeDisplayType": None,
        "NoticeSearchTotalLabelId": "noticeSearchTotal",
        "TypeOfCompetitions": [],
    }


def post_page(session: requests.Session, page_index: int) -> requests.Response:
    last = None
    for attempt in range(REQUEST_RETRIES):
        try:
            r = session.post(SEARCH_URL, json=payload(page_index), timeout=60)
            last = r
            if r.status_code in {408, 425, 429} or r.status_code >= 500:
                if attempt + 1 < REQUEST_RETRIES:
                    time.sleep(min(16, 2 ** attempt))
                    continue
            r.raise_for_status()
            return r
        except Exception:
            if attempt + 1 >= REQUEST_RETRIES:
                raise
            time.sleep(min(16, 2 ** attempt))
    if last is not None:
        last.raise_for_status()
    raise RuntimeError(f"UNGM public search page {page_index} failed")


def extract_total(html: str) -> int | None:
    text = clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    m = TOTAL_RE.search(text)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return None
    # Some renders keep the count in a dedicated element without the label text.
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id=re.compile(r"noticeSearchTotal", re.I))
    if node:
        m = re.search(r"[\d,]+", clean(node.get_text(" ", strip=True)))
        if m:
            try:
                return int(m.group(0).replace(",", ""))
            except Exception:
                pass
    return None


def parse_rows(html: str, page_index: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(".tableRow")
    rows = []
    seen = set()
    for node in nodes:
        notice_id = clean(node.get("data-noticeid"))
        href = ""
        title = ""
        for a in node.select("a[href]"):
            candidate_href = clean(a.get("href"))
            m = NOTICE_RE.search(candidate_href)
            if m:
                notice_id = notice_id or m.group(1)
                href = candidate_href
                title = clean(a.get_text(" ", strip=True)) or title
                break
        if not notice_id or notice_id in seen:
            continue
        seen.add(notice_id)
        cells = [clean(x.get_text(" ", strip=True)) for x in node.select(".tableCell")]
        row_text = clean(node.get_text(" ", strip=True))

        # Current UNGM grid order is: utility/title, deadline, published,
        # organization, opportunity type, reference, beneficiary country.
        # Keep row-text fallbacks so a cosmetic extra column does not drop data.
        if not title:
            title = cells[1] if len(cells) > 1 else row_text[:700]
        deadline = parse_date(cells[2]) if len(cells) > 2 else None
        published = parse_date(cells[3]) if len(cells) > 3 else None
        buyer = cells[4] if len(cells) > 4 else None
        opportunity_type = cells[5] if len(cells) > 5 else None
        reference = cells[6] if len(cells) > 6 else None
        country = cells[7] if len(cells) > 7 else None

        if deadline is None:
            dates = [parse_date(m.group(1)) for m in DATE_RE.finditer(row_text)]
            dates = [d for d in dates if d]
            if dates:
                # Public search is constrained by DeadlineFrom=today. The first
                # date in result rows is the deadline in the current UNGM grid.
                deadline = dates[0]
                if len(dates) > 1 and published is None:
                    published = dates[1]
        if deadline and deadline < NOW.replace(hour=0, minute=0, second=0, microsecond=0):
            continue

        rows.append({
            "candidate_id": f"UNGM:{notice_id}",
            "source": "UNGM_PUBLIC",
            "portal": "UNGM",
            "notice_id": notice_id,
            "title": title or row_text[:700],
            "buyer": buyer or None,
            "country": country or None,
            "deadline": deadline.isoformat() if deadline else None,
            "published": published.isoformat() if published else None,
            "current": True,
            "currentness_evidence": "UNGM_PUBLIC_SEARCH_DEADLINE_FROM_TODAY",
            "notice_type": opportunity_type or None,
            "reference": reference or None,
            "notice_url": urljoin(LIST_URL, href) if href else f"{BASE}/Public/Notice/{notice_id}",
            "description": row_text,
            "route": {"notice_id": notice_id},
            "search_page_index": page_index,
            "discovered_at": NOW.isoformat(),
        })
    return rows


def persist(records, *, pages_fetched, total_reported, exhausted, errors, telemetry):
    rows = sorted(records.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", rows)
    count_ok = total_reported is None or len(rows) >= total_reported
    complete = bool(exhausted and not errors and rows and count_ok)
    stats = {
        "source": "UNGM_PUBLIC",
        "portal": "UNGM",
        "listing_contract": "UNGM_PUBLIC_SEARCH_POST_V3",
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "pages_fetched": pages_fetched,
        "page_size": PAGE_SIZE,
        "total_reported": total_reported,
        "enumeration_exhausted": exhausted,
        "enumeration_complete": complete,
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": complete,
        "errors": errors,
        "warnings": [],
        "telemetry": telemetry,
        "generated_at": NOW.isoformat(),
        "source_url": LIST_URL,
        "search_url": SEARCH_URL,
        "semantics": "Uses UNGM's public Procurement Opportunities POST search contract with DeadlineFrom=today and PageIndex/PageSize. Traversal is complete only after the first empty result page; an observed total, when exposed, must also be satisfied.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "text/html, */*; q=0.01",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LIST_URL,
    })
    # Establish public session/cookies before using the grid endpoint.
    errors = []
    telemetry = {"list_url": LIST_URL, "search_url": SEARCH_URL, "deadline_from": payload(0)["DeadlineFrom"], "pages": []}
    try:
        landing = session.get(LIST_URL, timeout=60)
        telemetry["landing_status"] = landing.status_code
        landing.raise_for_status()
    except Exception as exc:
        errors.append({"type": "LANDING_REQUEST_FAILED", "error": repr(exc)})

    records = {}
    pages_fetched = 0
    exhausted = False
    total_reported = None
    if not errors:
        for page_index in range(MAX_PAGES):
            try:
                r = post_page(session, page_index)
            except Exception as exc:
                errors.append({"type": "PUBLIC_SEARCH_REQUEST_FAILED", "page_index": page_index, "error": repr(exc)})
                break
            pages_fetched += 1
            if total_reported is None:
                total_reported = extract_total(r.text)
            page_rows = parse_rows(r.text, page_index)
            telemetry["pages"].append({"page_index": page_index, "rows": len(page_rows), "bytes": len(r.content), "status": r.status_code})
            if not page_rows:
                exhausted = True
                telemetry["exhaustion_proof"] = "FIRST_EMPTY_PUBLIC_SEARCH_PAGE"
                break
            before = len(records)
            for row in page_rows:
                records[row["candidate_id"]] = row
            if len(records) == before:
                errors.append({"type": "REPEATED_RESULT_SET", "page_index": page_index, "materialized": len(records)})
                break
            persist(records, pages_fetched=pages_fetched, total_reported=total_reported, exhausted=False, errors=errors, telemetry=telemetry)
            if PAGE_DELAY_SECONDS:
                time.sleep(PAGE_DELAY_SECONDS)
        else:
            errors.append({"type": "HARD_PAGE_CAP_REACHED", "max_pages": MAX_PAGES})

    stats = persist(records, pages_fetched=pages_fetched, total_reported=total_reported, exhausted=exhausted, errors=errors, telemetry=telemetry)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
