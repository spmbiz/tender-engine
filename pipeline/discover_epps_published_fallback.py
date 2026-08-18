from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL = os.environ["EPPS_BASE_URL"].rstrip("/")
SOURCE = os.environ["EPPS_SOURCE"].strip().upper()
PREFIX = os.getenv("EPPS_ID_PREFIX", SOURCE).strip()
TZ = ZoneInfo(os.getenv("EPPS_TIMEZONE", "Europe/Brussels"))
OUT = Path(os.getenv("DISCOVERY_OUT", f"discovery/global/{SOURCE}"))
OUT.mkdir(parents=True, exist_ok=True)
MAX_PAGES = max(1, int(os.getenv("EPPS_PUBLISHED_MAX_PAGES", "160")))
LOOKBACK_DAYS = max(30, int(os.getenv("EPPS_PUBLISHED_LOOKBACK_DAYS", "240")))
DETAIL_BUDGET = max(0, int(os.getenv("EPPS_PUBLISHED_DETAIL_BUDGET", "300")))
NOW = datetime.now(TZ)
CUTOFF = NOW - timedelta(days=LOOKBACK_DAYS)
S = requests.Session()
S.headers.update({"User-Agent": "Tender-Engine/6.7 public procurement research", "Accept": "text/html,application/xhtml+xml,*/*"})
RESOURCE_RE = re.compile(r"resourceId=(\d+)", re.I)
AWARD_RE = re.compile(r"award notice|contract award|γνωστοποίηση συναφθείσας|ανάθεση", re.I)
COMPETITION_RE = re.compile(
    r"contract notice|corrigendum|prior information|pre-information|"
    r"προκήρυξη σύμβασης|διορθωτική προκήρυξη|προκήρυξη τροποποίησης|"
    r"γνωστοποίηση σύμβασης|προκήρυξη διαγωνισμού",
    re.I,
)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\b")


def clean(v):
    return " ".join(str(v or "").split())


def fetch(url):
    last = None
    for attempt in range(4):
        try:
            r = S.get(url, timeout=45, allow_redirects=True)
            last = r
            if r.status_code in (408, 425, 429) or r.status_code >= 500:
                if attempt < 3:
                    time.sleep(min(12, 2 ** attempt))
                    continue
            r.raise_for_status()
            return r
        except Exception:
            if attempt == 3:
                raise
            time.sleep(min(8, 2 ** attempt))
    if last is not None:
        last.raise_for_status()
    raise RuntimeError(url)


def parse_dt(text):
    text = clean(text)
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    m = DATE_RE.search(text)
    if m:
        raw = m.group(1) + ((" " + m.group(2)) if m.group(2) else "")
        return parse_dt(raw) if raw != text else None
    return None


def all_dates(text):
    out = []
    for m in DATE_RE.finditer(clean(text)):
        raw = m.group(1) + ((" " + m.group(2)) if m.group(2) else "")
        dt = parse_dt(raw)
        if dt:
            out.append(dt)
    return out


def headers(soup):
    best = []
    for tr in soup.find_all("tr"):
        h = [clean(x.get_text(" ", strip=True)).lower() for x in tr.find_all("th")]
        if len(h) > len(best):
            best = h
    return best


def pick(cells, hs, needles):
    for i, h in enumerate(hs):
        if any(n in h for n in needles) and i < len(cells):
            return cells[i]
    return None


def choose_title(cells, mapped, row_text):
    if mapped and len(clean(mapped)) > 4 and not COMPETITION_RE.search(mapped):
        return clean(mapped)
    candidates = []
    for cell in cells:
        text = clean(cell)
        if len(text) < 8 or COMPETITION_RE.search(text) or AWARD_RE.search(text):
            continue
        if DATE_RE.fullmatch(text) or re.fullmatch(r"(?:EN|EL|MT|Published|Δημοσιεύθηκε)", text, re.I):
            continue
        candidates.append(text)
    return max(candidates, key=len) if candidates else clean(row_text)[:1200]


def load_authority_seeds():
    seeds = []
    candidates = []
    raw = os.getenv("EPPS_AUTHORITY_SEEDS_JSON", "").strip()
    if raw:
        try:
            candidates.extend(json.loads(raw))
        except Exception:
            pass
    control = Path("control/cyprus_epps_authority_seeds.json")
    if SOURCE == "CYPRUS_EPPS" and control.exists():
        try:
            obj = json.loads(control.read_text(encoding="utf-8"))
            candidates.extend(obj.get("authorities") if isinstance(obj, dict) else obj)
        except Exception:
            pass
    seen = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("authority_id") or item.get("authorityId") or "").strip()
        gid = str(item.get("org_group_id") or item.get("orgGroupId") or "").strip()
        if not (aid.isdigit() and gid.isdigit()):
            continue
        pair = (aid, gid)
        if pair not in seen:
            seen.add(pair)
            seeds.append(pair)
    return seeds


def published_url(page, authority=None):
    params = {"d-446978-n": "1", "d-446978-o": "1", "d-446978-p": str(page), "d-446978-s": "datePublished"}
    if SOURCE == "MALTA_EPPS":
        params["orgGroupId"] = "5776"
    elif authority:
        params["authorityId"], params["orgGroupId"] = authority
    return f"{BASE_URL}/epps/notices/viewPublishedNotices.do?{urlencode(params)}"


def detail_workspace(resource_id):
    url = f"{BASE_URL}/epps/cft/prepareViewCfTWS.do?resourceId={resource_id}"
    try:
        r = fetch(url)
        soup = BeautifulSoup(r.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        deadline = None
        markers = (
            "time-limit for receipt of tenders or requests to participate",
            "time limit for receipt of tenders or requests to participate",
            "deadline",
            "closing date",
            "submission deadline",
            "καταληκτική ημερομηνία υποβολής προσφορών",
            "καταληκ",
        )
        lower = text.lower()
        for marker in markers:
            pos = lower.find(marker.lower())
            if pos >= 0:
                value = parse_dt(text[pos:pos + 500])
                if value:
                    deadline = value
                    break
        buyer = None
        for pattern in (
            r"Name of Contracting Authority:\s*(.+?)(?:Published on behalf of:|Original CA name:|Title:)",
            r"Όνομα Αναθέτουσας Αρχής:\s*(.+?)(?:Τίτλος:|Μοναδικός Αριθμός Διαγωνισμού:)",
        ):
            m = re.search(pattern, text, re.I)
            if m:
                buyer = clean(m.group(1))[:1000]
                break
        cpvs = []
        for code in re.findall(r"\b\d{8}(?:-\d)?\b", text):
            if code not in cpvs:
                cpvs.append(code)
        value = None
        vm = re.search(r"Estimated Contract Value \(EUR\):\s*([\d,. ]+)", text, re.I)
        if vm:
            try:
                value = float(vm.group(1).replace(" ", "").replace(",", ""))
            except ValueError:
                pass
        return {"deadline": deadline, "text": text[:10000], "buyer": buyer, "cpv": cpvs[:20], "estimated_value": value, "url": url}
    except Exception:
        return {"deadline": None, "text": None, "buyer": None, "cpv": [], "estimated_value": None, "url": url}


def read_existing():
    out = {}
    path = OUT / "current.jsonl"
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("candidate_id"):
            out[str(row["candidate_id"])] = row
    return out


def write_rows(records):
    rows = sorted(records.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    for name in ("raw.jsonl", "current.jsonl"):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def main():
    records = read_existing()
    errors = []
    warnings = []
    pages = 0
    detail_budget = DETAIL_BUDGET
    detail_calls = 0
    cutoff_reached = False
    parsed_competition_rows = 0
    rid_rows = 0

    authorities = load_authority_seeds() if SOURCE == "CYPRUS_EPPS" else [None]
    if SOURCE == "CYPRUS_EPPS" and not authorities:
        warnings.append({"type": "CYPRUS_AUTHORITY_SEEDS_MISSING", "coverage_credit": False})
        authorities = [None]

    authority_stats = []
    for authority in authorities:
        authority_pages = 0
        authority_cutoff = False
        authority_rows = 0
        for page in range(1, MAX_PAGES + 1):
            url = published_url(page, authority)
            try:
                r = fetch(url)
            except Exception as exc:
                errors.append({"page": page, "authority": authority, "url": url, "error": repr(exc)})
                break
            soup = BeautifulSoup(r.text, "html.parser")
            hs = headers(soup)
            page_rows = 0
            oldest_pub = None
            trs = soup.find_all("tr")

            for tr in trs:
                cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
                if len(cells) < 4:
                    continue
                row_text = clean(tr.get_text(" ", strip=True))
                if AWARD_RE.search(row_text) or not COMPETITION_RE.search(row_text):
                    continue
                parsed_competition_rows += 1

                rid = None
                notice_href = None
                for a in tr.find_all("a", href=True):
                    href = a.get("href") or ""
                    m = RESOURCE_RE.search(href)
                    if m:
                        rid = m.group(1)
                        notice_href = urljoin(r.url, href)
                        break
                if not rid:
                    m = RESOURCE_RE.search(str(tr))
                    rid = m.group(1) if m else None
                if not rid:
                    continue
                rid_rows += 1

                mapped_type = pick(cells, hs, ("type", "τύπος"))
                title = choose_title(cells, pick(cells, hs, ("title", "τίτλος")), row_text)
                dates = all_dates(row_text)
                pub_raw = pick(cells, hs, ("date pub", "ημερομηνία δημοσίευσης"))
                pub = parse_dt(pub_raw) if pub_raw else (dates[-1] if dates else None)
                if pub and (oldest_pub is None or pub < oldest_pub):
                    oldest_pub = pub
                if pub and pub < CUTOFF:
                    continue

                # Published Notices "Submission Date" is a notice-workflow date,
                # not the tender bid deadline. Preserve it only as provenance.
                published_submission_raw = pick(cells, hs, ("submission", "ημερομηνία υποβολής"))
                published_submission = parse_dt(published_submission_raw) if published_submission_raw else (dates[0] if dates else None)

                workspace = None
                deadline = None
                if detail_budget > 0:
                    workspace = detail_workspace(rid)
                    detail_budget -= 1
                    detail_calls += 1
                    deadline = workspace.get("deadline")
                if deadline and deadline < NOW:
                    continue

                detail_url = f"{BASE_URL}/epps/cft/prepareViewCfTWS.do?resourceId={rid}"
                cid = f"{PREFIX}:{rid}"
                records[cid] = {
                    "candidate_id": cid,
                    "source": SOURCE,
                    "portal": SOURCE,
                    "resource_id": rid,
                    "notice_id": rid,
                    "title": title,
                    "buyer": workspace.get("buyer") if workspace else None,
                    "country": "MT" if SOURCE == "MALTA_EPPS" else ("CY" if SOURCE == "CYPRUS_EPPS" else None),
                    "deadline": deadline.isoformat() if deadline else None,
                    "published": pub.isoformat() if pub else None,
                    "published_notice_submission_date": published_submission.isoformat() if published_submission else None,
                    "current": True,
                    "currentness_evidence": "EPPS_CFT_WORKSPACE_FUTURE_DEADLINE" if deadline else "EPPS_RECENT_PUBLISHED_COMPETITION_NOTICE_DEADLINE_UNKNOWN",
                    "notice_url": notice_href or detail_url,
                    "description": (workspace.get("text") if workspace else None) or row_text,
                    "cpv": workspace.get("cpv") if workspace else [],
                    "estimated_value": workspace.get("estimated_value") if workspace else None,
                    "notice_type": clean(mapped_type) or None,
                    "currency": "EUR",
                    "route": {
                        "resource_id": rid,
                        "base_url": BASE_URL,
                        "detail_url": detail_url,
                        "documents_url": f"{BASE_URL}/epps/cft/listContractDocuments.do?resourceId={rid}",
                    },
                    "discovered_at": NOW.isoformat(),
                    "fallback_source": "PUBLISHED_NOTICES",
                    "authority_seed": {"authority_id": authority[0], "org_group_id": authority[1]} if authority else None,
                }
                page_rows += 1
                authority_rows += 1

            pages += 1
            authority_pages += 1
            if oldest_pub and oldest_pub < CUTOFF:
                cutoff_reached = True
                authority_cutoff = True
                break
            if not trs or (page_rows == 0 and page > 1):
                break
        authority_stats.append({"authority": authority, "pages": authority_pages, "cutoff_reached": authority_cutoff, "current_rows": authority_rows})

    rows = write_rows(records)
    warnings.append({
        "type": "PUBLISHED_NOTICES_RECALL_FALLBACK",
        "pages": pages,
        "lookback_days": LOOKBACK_DAYS,
        "cutoff_reached": cutoff_reached,
        "detail_calls": detail_calls,
        "authority_seed_count": len([x for x in authorities if x]),
        "coverage_credit": False,
    })
    stats = {
        "source": SOURCE,
        "base_url": BASE_URL,
        "listing_contract": "EPPS_PUBLISHED_NOTICES_RECALL_FALLBACK_V4_WORKSPACE_DEADLINE",
        "current_materialized": len(rows),
        "raw_materialized": len(rows),
        "published_fallback_pages": pages,
        "competition_rows_seen": parsed_competition_rows,
        "competition_rows_with_resource_id": rid_rows,
        "deadline_parsed": sum(1 for r in rows if r.get("deadline")),
        "enumeration_exhausted": False,
        "enumeration_complete": False,
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": False,
        "errors": errors,
        "warnings": warnings,
        "authority_stats": authority_stats,
        "generated_at": NOW.isoformat(),
        "semantics": "Published Notices is recall reconstruction only. Its Submission Date is explicitly NOT treated as the bid deadline. The authoritative tender deadline is resolved from the public CfT workspace via resourceId; recent unresolved notices remain UNKNOWN rather than being assumed expired. Cyprus uses only verified public authority seeds.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not rows:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
