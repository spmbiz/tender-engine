from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

OUT = Path(os.getenv("CY_GLOBAL_PUBLISHED_PROBE_OUT", "control/cy_global_published_pager_probe.json"))
START_URL = "https://www.eprocurement.gov.cy/epps/notices/viewPublishedNotices.do"
UA = "Tender-Engine/7.4 (+public procurement research; Cyprus national Published Notices pager probe)"
TOTAL_PATTERNS = [
    re.compile(r"(?:results?|records?|notices?)\s*[:\-]?\s*([\d,. ]{2,})", re.I),
    re.compile(r"(?:of|από)\s+([\d,. ]{2,})", re.I),
]
RESOURCE_RE = re.compile(r"[?&]resourceId=(\d+)", re.I)
NOTICE_RE = re.compile(r"[?&]noticeId=(\d+)", re.I)
DOCUMENT_RE = re.compile(r"[?&]documentId=(\d+)", re.I)


def clean(value):
    return " ".join(str(value or "").split())


def integer(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def fetch(session: requests.Session, url: str):
    response = session.get(url, timeout=60, allow_redirects=True)
    response.raise_for_status()
    return response


def parse_total(soup: BeautifulSoup) -> int | None:
    text = clean(soup.get_text(" ", strip=True))
    candidates: list[int] = []
    for pattern in TOTAL_PATTERNS:
        for match in pattern.finditer(text):
            value = integer(match.group(1))
            if value and value >= 10:
                candidates.append(value)
    # DisplayTag totals can also appear as plain text near pager spans.
    for node in soup.find_all(["span", "div", "td"]):
        node_text = clean(node.get_text(" ", strip=True))
        if not re.search(r"result|record|notice|page|σελίδ", node_text, re.I):
            continue
        for token in re.findall(r"\b\d[\d,. ]{2,}\b", node_text):
            value = integer(token)
            if value and value >= 10:
                candidates.append(value)
    return max(candidates) if candidates else None


def notice_rows(soup: BeautifulSoup, base_url: str):
    rows = []
    for tr in soup.find_all("tr"):
        links = []
        resource_ids = set()
        notice_ids = set()
        document_ids = set()
        for a in tr.find_all("a", href=True):
            absolute = urljoin(base_url, a.get("href") or "")
            if "viewPublished" not in absolute and "resourceId=" not in absolute:
                continue
            links.append(absolute)
            m = RESOURCE_RE.search(absolute)
            if m:
                resource_ids.add(m.group(1))
            m = NOTICE_RE.search(absolute)
            if m:
                notice_ids.add(m.group(1))
            m = DOCUMENT_RE.search(absolute)
            if m:
                document_ids.add(m.group(1))
        if not links:
            continue
        text = clean(tr.get_text(" ", strip=True))
        rows.append({
            "text": text[:2000],
            "links": list(dict.fromkeys(links))[:8],
            "resource_ids": sorted(resource_ids),
            "notice_ids": sorted(notice_ids),
            "document_ids": sorted(document_ids),
        })
    return rows


def pager_candidates(soup: BeautifulSoup, base_url: str):
    candidates = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        absolute = urljoin(base_url, href)
        parsed = urlsplit(absolute)
        if "viewPublishedNotices.do" not in parsed.path:
            continue
        query = parse_qs(parsed.query)
        # DisplayTag uses generated keys like d-446978-p. We deliberately do not
        # assume the hash; detect any page-number key ending in '-p'.
        page_keys = {k: v for k, v in query.items() if k.endswith("-p") and v}
        if not page_keys:
            continue
        identity = absolute
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append({
            "text": clean(a.get_text(" ", strip=True)),
            "url": absolute,
            "page_keys": page_keys,
        })
    return candidates


def choose_next(candidates, current_url: str):
    current = urlsplit(current_url)
    current_qs = parse_qs(current.query)
    current_page = 1
    for key, values in current_qs.items():
        if key.endswith("-p") and values:
            try:
                current_page = int(values[0])
            except Exception:
                pass
    numeric = []
    for item in candidates:
        pages = []
        for values in item["page_keys"].values():
            for value in values:
                try:
                    pages.append(int(value))
                except Exception:
                    pass
        if pages:
            page = min(pages)
            if page > current_page:
                numeric.append((page, item))
    if numeric:
        numeric.sort(key=lambda x: x[0])
        return numeric[0][1]
    for item in candidates:
        if re.search(r"next|suivant|επόμε|›|»|>", item.get("text") or "", re.I):
            return item
    return None


def page_snapshot(response):
    soup = BeautifulSoup(response.text, "html.parser")
    rows = notice_rows(soup, response.url)
    pagers = pager_candidates(soup, response.url)
    return {
        "url": response.url,
        "status": response.status_code,
        "bytes": len(response.content),
        "title": clean(soup.title.get_text(" ", strip=True)) if soup.title else None,
        "total_reported": parse_total(soup),
        "notice_row_count": len(rows),
        "resource_id_count": len({rid for row in rows for rid in row["resource_ids"]}),
        "resource_ids": sorted({rid for row in rows for rid in row["resource_ids"]})[:50],
        "notice_ids": sorted({nid for row in rows for nid in row["notice_ids"]})[:50],
        "document_ids": sorted({did for row in rows for did in row["document_ids"]})[:50],
        "row_sample": rows[:5],
        "pager_candidates": pagers[:40],
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
    }, soup, pagers


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"})
    pages = []
    errors = []
    url = START_URL
    seen_urls = set()

    for index in range(3):
        if url in seen_urls:
            errors.append({"stage": "pager", "error": "REPEATED_URL", "url": url})
            break
        seen_urls.add(url)
        try:
            response = fetch(session, url)
            snapshot, _soup, candidates = page_snapshot(response)
            snapshot["sequence_index"] = index + 1
            pages.append(snapshot)
            if index < 2:
                nxt = choose_next(candidates, response.url)
                if not nxt:
                    errors.append({"stage": "pager", "error": "NO_NEXT_PAGER_LINK", "url": response.url})
                    break
                url = nxt["url"]
        except Exception as exc:
            errors.append({"stage": "fetch", "url": url, "error": repr(exc)})
            break

    totals = [p.get("total_reported") for p in pages if p.get("total_reported") is not None]
    stable_total = bool(len(totals) == len(pages) == 3 and len(set(totals)) == 1)
    distinct_pages = len({p.get("body_sha256") for p in pages}) == len(pages) == 3
    all_have_rows = all(int(p.get("notice_row_count") or 0) > 0 for p in pages)
    all_have_resource_ids = all(int(p.get("resource_id_count") or 0) > 0 for p in pages)
    pager_key_samples = sorted({
        key
        for p in pages
        for item in p.get("pager_candidates") or []
        for key in (item.get("page_keys") or {}).keys()
    })

    payload = {
        "schema": "CY_EPPS_GLOBAL_PUBLISHED_PAGER_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_url": START_URL,
        "pages": pages,
        "stable_total": stable_total,
        "total_reported": totals[0] if stable_total else None,
        "distinct_pages": distinct_pages,
        "all_pages_have_notice_rows": all_have_rows,
        "all_pages_have_resource_ids": all_have_resource_ids,
        "pager_parameter_keys": pager_key_samples,
        "errors": errors,
        "pass": bool(not errors and stable_total and distinct_pages and all_have_rows and all_have_resource_ids),
        "semantics": (
            "Read-only traversal probe of Cyprus ePPS national Published Notices without authority/orgGroup filters. "
            "Pagination URLs are followed exactly from the publisher-provided HTML anchors; no generated DisplayTag hash or page parameter is guessed. "
            "A passing proof requires three distinct sequential pages, stable official total, notice rows and resourceId identities on every page. No CAPTCHA or Current Opportunities page is accessed."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
