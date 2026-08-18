from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UNGM_PUBLIC"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://www.ungm.org"
LIST_URL = BASE + "/Public/Notice"
SEARCH_PATH = "/Public/Notice/Search"
NOW = datetime.now(timezone.utc)
PAGE_SIZE = 15
MAX_PAGES = max(1, int(os.getenv("UNGM_MAX_PAGES", "2000")))
WAIT_MS = max(200, int(os.getenv("UNGM_PAGE_WAIT_MS", "350")))
NOTICE_RE = re.compile(r"/Public/Notice/(\d+)(?:\b|/|\?)", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}-[A-Za-z]{3}-20\d{2}|\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})\b")
TOTAL_RE = re.compile(r"Displaying\s+results\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)", re.I)
UA = "Tender-Engine/6.9 (+public procurement research; UNGM public browser-session search)"


def clean(value):
    return " ".join(str(value or "").split())


def parse_date(value):
    text = clean(value)
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    match = DATE_RE.search(text)
    if match and match.group(1) != text:
        return parse_date(match.group(1))
    return None


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def search_payload(page_index: int) -> dict:
    # This mirrors the public Procurement Opportunities grid contract. The
    # browser page itself performs this same-origin POST. DeadlineFrom=today
    # makes the live/open scope explicit instead of relying on UI defaults.
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


def unwrap_fragment(raw: str) -> str:
    text = raw or ""
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        obj = json.loads(stripped)
    except Exception:
        return text
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for key in ("html", "Html", "result", "Result", "content", "Content", "data", "Data"):
            value = obj.get(key)
            if isinstance(value, str):
                return value
    return text


def extract_total(text: str) -> int | None:
    plain = clean(BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True))
    match = TOTAL_RE.search(plain)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except Exception:
        return None


def parse_rows(fragment: str, page_index: int) -> list[dict]:
    soup = BeautifulSoup(fragment, "html.parser")
    nodes = soup.select(".tableRow")
    if not nodes:
        # Defensive fallback for minor class-name changes: any row containing an
        # official notice link is eligible for parsing.
        nodes = [a.find_parent(["tr", "div"]) for a in soup.select("a[href*='/Public/Notice/']")]
        nodes = [n for n in nodes if n is not None]

    rows = []
    seen = set()
    for node in nodes:
        notice_id = clean(node.get("data-noticeid")) if hasattr(node, "get") else ""
        href = ""
        title = ""
        for anchor in node.select("a[href]"):
            candidate_href = clean(anchor.get("href"))
            match = NOTICE_RE.search(candidate_href)
            if not match:
                continue
            notice_id = notice_id or match.group(1)
            href = candidate_href
            title = clean(anchor.get_text(" ", strip=True)) or title
            break
        if not notice_id or notice_id in seen:
            continue
        seen.add(notice_id)

        cells = [clean(cell.get_text(" ", strip=True)) for cell in node.select(".tableCell, td")]
        row_text = clean(node.get_text(" ", strip=True))
        # Current UNGM grid order observed on the public page is title/utility,
        # deadline, published, organization, opportunity type, reference,
        # beneficiary country. Fall back to row dates if a cosmetic column is
        # inserted.
        deadline = None
        published = None
        buyer = None
        opportunity_type = None
        reference = None
        country = None
        if cells:
            for cell in cells:
                d = parse_date(cell)
                if d and deadline is None:
                    deadline = d
                elif d and published is None:
                    published = d
            non_dates = [c for c in cells if c and parse_date(c) is None]
            # Prefer explicit text later, so these are intentionally conservative.
            if len(non_dates) >= 4:
                buyer = non_dates[-4]
                opportunity_type = non_dates[-3]
                reference = non_dates[-2]
                country = non_dates[-1]
        if deadline is None:
            dates = [parse_date(m.group(1)) for m in DATE_RE.finditer(row_text)]
            dates = [d for d in dates if d]
            if dates:
                deadline = dates[0]
                published = published or (dates[1] if len(dates) > 1 else None)

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


def persist(records, *, pages_fetched: int, total_reported: int | None, exhausted: bool, errors: list, telemetry: dict):
    rows = sorted(records.values(), key=lambda row: (row.get("deadline") or "9999", row["candidate_id"]))
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", rows)
    count_proof = total_reported is None or len(rows) >= total_reported
    complete = bool(exhausted and not errors and rows and count_proof)
    stats = {
        "source": "UNGM_PUBLIC",
        "portal": "UNGM",
        "listing_contract": "UNGM_PUBLIC_BROWSER_SESSION_SEARCH_V4",
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
        "search_path": SEARCH_PATH,
        "semantics": "UNGM public landing is opened in a real browser session, then the page performs same-origin public POST searches with PageIndex/PageSize and DeadlineFrom=today. This avoids treating browser-bot session requirements as an API failure. Traversal is complete only after the first empty search page; any exposed total must also be satisfied.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


async def browser_search(page, page_index: int) -> tuple[int, str, str]:
    result = await page.evaluate(
        """async ({path, payload}) => {
          const response = await fetch(path, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json; charset=UTF-8',
              'Accept': 'text/html, */*; q=0.01',
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(payload)
          });
          return {
            status: response.status,
            contentType: response.headers.get('content-type') || '',
            text: await response.text()
          };
        }""",
        {"path": SEARCH_PATH, "payload": search_payload(page_index)},
    )
    return int(result.get("status") or 0), str(result.get("contentType") or ""), str(result.get("text") or "")


async def main():
    records = {}
    errors = []
    pages_fetched = 0
    exhausted = False
    total_reported = None
    telemetry = {
        "list_url": LIST_URL,
        "search_path": SEARCH_PATH,
        "deadline_from": search_payload(0)["DeadlineFrom"],
        "pages": [],
    }

    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000}, user_agent=UA)
            response = await page.goto(LIST_URL, wait_until="domcontentloaded", timeout=90000)
            telemetry["landing_status"] = response.status if response else None
            if response and response.status >= 400:
                errors.append({"type": "LANDING_HTTP_ERROR", "status": response.status})
            await page.wait_for_timeout(WAIT_MS)
            try:
                landing_text = clean(await page.locator("body").inner_text())
                total_reported = extract_total(landing_text)
            except Exception:
                landing_text = ""

            if not errors:
                for page_index in range(MAX_PAGES):
                    try:
                        status, content_type, raw = await browser_search(page, page_index)
                    except Exception as exc:
                        errors.append({"type": "PUBLIC_SEARCH_BROWSER_FETCH_FAILED", "page_index": page_index, "error": repr(exc)})
                        break
                    pages_fetched += 1
                    fragment = unwrap_fragment(raw)
                    if total_reported is None:
                        total_reported = extract_total(fragment)
                    page_rows = parse_rows(fragment, page_index)
                    telemetry["pages"].append({
                        "page_index": page_index,
                        "rows": len(page_rows),
                        "status": status,
                        "content_type": content_type,
                        "bytes": len(raw.encode("utf-8", errors="ignore")),
                    })
                    if status >= 400:
                        errors.append({"type": "PUBLIC_SEARCH_HTTP_ERROR", "page_index": page_index, "status": status})
                        break
                    if not page_rows:
                        exhausted = True
                        telemetry["exhaustion_proof"] = "FIRST_EMPTY_SAME_ORIGIN_SEARCH_PAGE"
                        break
                    before = len(records)
                    for row in page_rows:
                        records[row["candidate_id"]] = row
                    if len(records) == before:
                        errors.append({"type": "REPEATED_RESULT_SET", "page_index": page_index, "materialized": len(records)})
                        break
                    persist(records, pages_fetched=pages_fetched, total_reported=total_reported, exhausted=False, errors=errors, telemetry=telemetry)
                    if WAIT_MS:
                        await page.wait_for_timeout(WAIT_MS)
                else:
                    errors.append({"type": "HARD_PAGE_CAP_REACHED", "max_pages": MAX_PAGES})
            await browser.close()
    except Exception as exc:
        errors.append({"type": "UNGM_BROWSER_SESSION_ERROR", "error": repr(exc)})

    stats = persist(records, pages_fetched=pages_fetched, total_reported=total_reported, exhausted=exhausted, errors=errors, telemetry=telemetry)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["enumeration_complete"]:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
