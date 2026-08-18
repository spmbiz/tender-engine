from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from playwright.async_api import async_playwright

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/AU_AUSTENDER"))
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc)
LIST_URL = "https://www.tenders.gov.au/?event=public.ATM.list"
RSS_URL = "https://www.tenders.gov.au/public_data/rss/rss.xml"
UA = "Tender-Engine/6.3 (+public procurement research; official AusTender current ATM feed)"


def clean(v):
    return " ".join(str(v or "").split())


def pdt(v):
    s = clean(v)
    for fmt in (
        "%d-%b-%Y %I:%M %p (ACT Local Time)", "%d-%b-%Y %I:%M %p", "%d-%b-%Y",
        "%d/%m/%Y", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return clean(text)


def atm_id_from(link: str, title: str, description: str, guid: str) -> str:
    query = parse_qs(urlparse(link).query)
    for key in ("ATMUUID", "atmuuid", "ATMID", "atmId", "atmID", "id"):
        vals = query.get(key)
        if vals and clean(vals[0]):
            return clean(vals[0])
    hay = " | ".join((guid, title, description))
    for pattern in (
        r"\bATM\s*(?:ID|Reference|Ref)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{3,})\b",
        r"\bReference\s*[:#-]\s*([A-Z0-9][A-Z0-9._/-]{3,})\b",
    ):
        m = re.search(pattern, hay, re.I)
        if m:
            return m.group(1)
    stable = link or guid or (title + description)
    return "URL-" + hashlib.sha256(stable.encode("utf-8", errors="ignore")).hexdigest()[:24]


def deadline_from_text(text: str):
    candidates = re.findall(
        r"(?:Close(?:s| Date)?|Closing(?: Date)?|Deadline)\s*[:\-]?\s*([^|;]{6,80})",
        text,
        re.I,
    )
    for raw in candidates:
        raw = clean(raw)
        for candidate in (raw, raw[:30]):
            dt = pdt(candidate)
            if dt:
                return dt
        m = re.search(r"(\d{1,2}[-/]\w{3}[-/]20\d{2}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?)", raw, re.I)
        if m:
            dt = pdt(m.group(1))
            if dt:
                return dt
    return None


def persist(records, telemetry, errors, warnings):
    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    cur = [x for x in rows if x.get("current", True)]
    for fn, data in (("raw.jsonl", rows), ("current.jsonl", cur)):
        with (OUT / fn).open("w", encoding="utf-8") as f:
            for x in data:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    complete = bool(rows and not errors and telemetry.get("enumeration_exhausted"))
    stats = {
        "source": "AU_AUSTENDER",
        "raw_materialized": len(rows),
        "current_materialized": len(cur),
        "enumeration_exhausted": bool(telemetry.get("enumeration_exhausted")),
        "enumeration_complete": complete,
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "warnings": warnings,
        "official_url": LIST_URL,
        "official_rss_url": RSS_URL,
        "freshness_contract": "OFFICIAL_CURRENT_ATM_RSS_UPDATED_DAILY_AFTER_BUSINESS_HOURS_WHEN_RSS_PATH_USED",
        "telemetry": telemetry,
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return stats


def harvest_rss(records: dict, telemetry: dict, warnings: list) -> bool:
    try:
        response = requests.get(
            RSS_URL,
            timeout=60,
            headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5"},
        )
        telemetry["rss_http_status"] = response.status_code
        if response.status_code >= 400:
            warnings.append({"type": "RSS_HTTP_BLOCK", "status": response.status_code})
            return False
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        telemetry["rss_items_seen"] = len(items)
        if not items:
            warnings.append({"type": "RSS_ZERO_ITEMS"})
            return False
        for item in items:
            values = {child.tag.rsplit("}", 1)[-1].lower(): clean(child.text) for child in list(item)}
            title = values.get("title") or ""
            link = values.get("link") or values.get("guid") or ""
            guid = values.get("guid") or ""
            desc_raw = values.get("description") or ""
            desc = strip_html(desc_raw)
            pub = pdt(values.get("pubdate"))
            deadline = deadline_from_text(desc)
            atm = atm_id_from(link, title, desc, guid)
            cid = f"AU:{atm}"
            records[cid] = {
                "candidate_id": cid,
                "source": "AU_AUSTENDER",
                "portal": "AU_AUSTENDER",
                "notice_id": atm,
                "title": title or desc[:500],
                "buyer": None,
                "deadline": deadline.isoformat() if deadline else None,
                "published": pub.isoformat() if pub else None,
                "current": True if deadline is None else deadline >= NOW,
                "currentness_evidence": "AUSTENDER_CURRENT_ATM_RSS_SCOPE" if deadline is None else "RSS_SCOPE_PLUS_PARSED_DEADLINE",
                "notice_url": urljoin("https://www.tenders.gov.au/", link),
                "description": desc,
                "route": {"document_urls": []},
                "discovered_at": NOW.isoformat(),
            }
        telemetry["enumeration_mode"] = "OFFICIAL_CURRENT_ATM_RSS"
        telemetry["enumeration_exhausted"] = True
        return bool(records)
    except Exception as exc:
        warnings.append({"type": "RSS_ERROR", "message": repr(exc)})
        return False


async def harvest_browser(records: dict, telemetry: dict, errors: list) -> None:
    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            resp = await page.goto(LIST_URL, wait_until="domcontentloaded", timeout=90000)
            telemetry["browser_http_status"] = resp.status if resp else None
            await page.wait_for_timeout(2500)
            telemetry["page_title"] = await page.title()
            telemetry["html_bytes"] = len(await page.content())
            if resp and resp.status >= 400:
                errors.append({"type": "PUBLIC_SOURCE_HTTP_BLOCK", "status": resp.status, "message": f"AusTender public listing returned HTTP {resp.status}"})
                await browser.close()
                return
            rows = page.locator("tr")
            n = await rows.count()
            telemetry["table_rows_seen"] = n
            for i in range(n):
                tr = rows.nth(i)
                cells = tr.locator("td")
                cc = await cells.count()
                if cc < 3:
                    continue
                vals = [clean(await cells.nth(j).inner_text()) for j in range(cc)]
                links = tr.locator("a[href]")
                lc = await links.count()
                href = None
                text_link = None
                for j in range(lc):
                    a = links.nth(j)
                    h = await a.get_attribute("href")
                    t = clean(await a.inner_text())
                    if h and ("ATM" in h.upper() or "ATM" in t.upper() or "view" in h.lower()):
                        href, text_link = h, t
                        break
                if not href and lc:
                    href = await links.nth(0).get_attribute("href")
                    text_link = clean(await links.nth(0).inner_text())
                joined = " | ".join(vals)
                if not href or len(joined) < 20:
                    continue
                link = urljoin("https://www.tenders.gov.au/", href)
                atm = atm_id_from(link, text_link or "", joined, "")
                deadline = None
                for dv in reversed([v for v in vals if re.search(r"\b20\d{2}\b", v)]):
                    x = pdt(dv)
                    if x:
                        deadline = x
                        break
                candidates = [v for v in vals if len(v) >= 5 and not re.fullmatch(r"[\d\s:./()-]+", v)]
                title = max(candidates, key=len) if candidates else joined[:500]
                cid = f"AU:{atm}"
                records[cid] = {
                    "candidate_id": cid,
                    "source": "AU_AUSTENDER",
                    "portal": "AU_AUSTENDER",
                    "notice_id": atm,
                    "title": title,
                    "buyer": None,
                    "deadline": deadline.isoformat() if deadline else None,
                    "published": None,
                    "current": not deadline or deadline >= NOW,
                    "currentness_evidence": "AUSTENDER_CURRENT_ATM_BROWSER_SCOPE",
                    "notice_url": link,
                    "description": joined,
                    "route": {"document_urls": []},
                    "discovered_at": NOW.isoformat(),
                }
            telemetry["enumeration_mode"] = "PUBLIC_CURRENT_ATM_BROWSER_SINGLE_VIEW"
            telemetry["enumeration_exhausted"] = bool(records)
            await browser.close()
    except Exception as exc:
        errors.append({"type": "BROWSER_ERROR", "message": repr(exc)})


async def main():
    records = {}
    telemetry = {"list_url": LIST_URL, "rss_url": RSS_URL}
    errors = []
    warnings = []

    if harvest_rss(records, telemetry, warnings):
        persist(records, telemetry, errors, warnings)
        return

    await harvest_browser(records, telemetry, errors)
    persist(records, telemetry, errors, warnings)


if __name__ == "__main__":
    asyncio.run(main())