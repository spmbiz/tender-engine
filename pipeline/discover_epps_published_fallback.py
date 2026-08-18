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
S.headers.update({"User-Agent": "Tender-Engine/6.5 public procurement research", "Accept": "text/html,application/xhtml+xml,*/*"})
RESOURCE_RE = re.compile(r"resourceId=(\d+)", re.I)
AWARD_RE = re.compile(r"award notice|contract award|γνωστοποίηση συναφθείσας|ανάθεση", re.I)
COMPETITION_RE = re.compile(r"contract notice|corrigendum|prior information|pre-information|προκήρυξη σύμβασης|διορθωτική προκήρυξη|προκήρυξη τροποποίησης", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\b")
AUTHORITY_URL_RE = re.compile(r"authorityId=(\d+).*?orgGroupId=(\d+)|orgGroupId=(\d+).*?authorityId=(\d+)", re.I)


def clean(v): return " ".join(str(v or "").split())

def fetch(url):
    last = None
    for attempt in range(4):
        try:
            r = S.get(url, timeout=45, allow_redirects=True); last = r
            if r.status_code in (408, 425, 429) or r.status_code >= 500:
                if attempt < 3: time.sleep(min(12, 2 ** attempt)); continue
            r.raise_for_status(); return r
        except Exception:
            if attempt == 3: raise
            time.sleep(min(8, 2 ** attempt))
    if last is not None: last.raise_for_status()
    raise RuntimeError(url)

def parse_dt(text):
    text = clean(text)
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError: pass
    m = DATE_RE.search(text)
    if m:
        raw = m.group(1) + ((" " + m.group(2)) if m.group(2) else "")
        return parse_dt(raw) if raw != text else None
    return None

def headers(soup):
    best = []
    for tr in soup.find_all("tr"):
        h = [clean(x.get_text(" ", strip=True)).lower() for x in tr.find_all("th")]
        if len(h) > len(best): best = h
    return best

def pick(cells, hs, needles):
    for i, h in enumerate(hs):
        if any(n in h for n in needles) and i < len(cells): return cells[i]
    return None

def load_authority_seeds():
    """Return only previously observed official authority/orgGroup pairs.

    This is a recall helper for Cyprus, never an exhaustion proof. Seeds may be
    supplied through EPPS_AUTHORITY_SEEDS_JSON or a repo control file and every
    seed must be a numeric pair from an official ePPS URL.
    """
    seeds = []
    raw = os.getenv("EPPS_AUTHORITY_SEEDS_JSON", "").strip()
    candidates = []
    if raw:
        try: candidates.extend(json.loads(raw))
        except Exception: pass
    control = Path("control/cyprus_epps_authority_seeds.json")
    if SOURCE == "CYPRUS_EPPS" and control.exists():
        try:
            obj = json.loads(control.read_text(encoding="utf-8"))
            candidates.extend(obj.get("authorities") if isinstance(obj, dict) else obj)
        except Exception:
            pass
    seen = set()
    for item in candidates:
        if not isinstance(item, dict): continue
        aid = str(item.get("authority_id") or item.get("authorityId") or "").strip()
        gid = str(item.get("org_group_id") or item.get("orgGroupId") or "").strip()
        if not (aid.isdigit() and gid.isdigit()): continue
        key = (aid, gid)
        if key not in seen:
            seen.add(key); seeds.append(key)
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
        # European Dynamics workspaces use these labels across Malta/Cyprus.
        markers = (
            "time-limit for receipt of tenders or requests to participate",
            "time limit for receipt of tenders or requests to participate",
            "deadline", "closing date", "submission deadline",
            "καταληκτική ημερομηνία υποβολής προσφορών", "καταληκ", "υποβολ",
        )
        lower = text.lower()
        for marker in markers:
            pos = lower.find(marker.lower())
            if pos >= 0:
                value = parse_dt(text[pos:pos + 420])
                if value:
                    deadline = value; break
        buyer = None
        for pattern in (
            r"Name of Contracting Authority:\s*(.+?)(?:Published on behalf of:|Original CA name:|Title:)",
            r"Όνομα Αναθέτουσας Αρχής:\s*(.+?)(?:Τίτλος:|Μοναδικός Αριθμός Διαγωνισμού:)",
        ):
            m = re.search(pattern, text, re.I)
            if m:
                buyer = clean(m.group(1))[:1000]; break
        cpvs = []
        for code in re.findall(r"\b\d{8}(?:-\d)?\b", text):
            if code not in cpvs: cpvs.append(code)
        value = None
        vm = re.search(r"Estimated Contract Value \(EUR\):\s*([\d,. ]+)", text, re.I)
        if vm:
            try: value = float(vm.group(1).replace(" ", "").replace(",", ""))
            except ValueError: pass
        return {"deadline": deadline, "text": text[:10000], "buyer": buyer, "cpv": cpvs[:20], "estimated_value": value, "url": url}
    except Exception:
        return {"deadline": None, "text": None, "buyer": None, "cpv": [], "estimated_value": None, "url": url}

def read_existing():
    out = {}
    path = OUT / "current.jsonl"
    if not path.exists(): return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try: row = json.loads(raw)
        except Exception: continue
        if isinstance(row, dict) and row.get("candidate_id"): out[str(row["candidate_id"])] = row
    return out

def write_rows(records):
    rows = sorted(records.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    for name in ("raw.jsonl", "current.jsonl"):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for row in rows: fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows

def main():
    records = read_existing(); errors = []; warnings = []; pages = 0; detail_budget = DETAIL_BUDGET; detail_calls = 0; cutoff_reached = False
    authorities = load_authority_seeds() if SOURCE == "CYPRUS_EPPS" else [None]
    if SOURCE == "CYPRUS_EPPS" and not authorities:
        warnings.append({"type": "CYPRUS_AUTHORITY_SEEDS_MISSING", "coverage_credit": False})
        # Preserve the old global probe as a diagnostic. It is known to be empty
        # on some production renders but may recover if the portal changes.
        authorities = [None]
    authority_stats = []
    for authority in authorities:
        authority_pages = 0; authority_cutoff = False
        for page in range(1, MAX_PAGES + 1):
            url = published_url(page, authority)
            try: r = fetch(url)
            except Exception as exc:
                errors.append({"page": page, "authority": authority, "url": url, "error": repr(exc)}); break
            soup = BeautifulSoup(r.text, "html.parser"); hs = headers(soup); page_rows = 0; oldest_pub = None
            trs = soup.find_all("tr")
            for tr in trs:
                cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
                if len(cells) < 5: continue
                typ = pick(cells, hs, ("type", "τύπος")) or cells[0]
                if AWARD_RE.search(typ) or not COMPETITION_RE.search(typ): continue
                title = pick(cells, hs, ("title", "τίτλος")) or (cells[1] if len(cells) > 1 else "")
                pub_raw = pick(cells, hs, ("date pub", "ημερομηνία δημοσίευσης")) or cells[-1]
                pub = parse_dt(pub_raw)
                if pub and (oldest_pub is None or pub < oldest_pub): oldest_pub = pub
                rid = None; notice_href = None
                for a in tr.find_all("a", href=True):
                    m = RESOURCE_RE.search(a.get("href") or "")
                    if m:
                        rid = m.group(1); notice_href = urljoin(r.url, a.get("href") or ""); break
                if not rid:
                    m = RESOURCE_RE.search(str(tr)); rid = m.group(1) if m else None
                if not rid: continue
                deadline = None; workspace = None
                submission = pick(cells, hs, ("submission", "ημερομηνία υποβολής"))
                if submission: deadline = parse_dt(submission)
                # For Cyprus the Published Notices table itself carries submission
                # date. For Malta resolve the public CfT workspace using resourceId.
                if (deadline is None or SOURCE == "MALTA_EPPS") and detail_budget > 0:
                    workspace = detail_workspace(rid); detail_budget -= 1; detail_calls += 1
                    deadline = workspace.get("deadline") or deadline
                if deadline and deadline < NOW: continue
                detail_url = f"{BASE_URL}/epps/cft/prepareViewCfTWS.do?resourceId={rid}"
                cid = f"{PREFIX}:{rid}"
                records[cid] = {
                    "candidate_id": cid, "source": SOURCE, "portal": SOURCE,
                    "resource_id": rid, "notice_id": rid, "title": clean(title),
                    "buyer": workspace.get("buyer") if workspace else None,
                    "country": "MT" if SOURCE == "MALTA_EPPS" else ("CY" if SOURCE == "CYPRUS_EPPS" else None),
                    "deadline": deadline.isoformat() if deadline else None,
                    "published": pub.isoformat() if pub else None, "current": True,
                    "currentness_evidence": "EPPS_PUBLISHED_NOTICE_FUTURE_DEADLINE" if deadline else "EPPS_RECENT_PUBLISHED_COMPETITION_NOTICE_DEADLINE_UNKNOWN",
                    "notice_url": notice_href or detail_url,
                    "description": (workspace.get("text") if workspace else None) or clean(tr.get_text(" ", strip=True)),
                    "cpv": workspace.get("cpv") if workspace else [],
                    "estimated_value": workspace.get("estimated_value") if workspace else None,
                    "notice_type": clean(typ), "currency": "EUR",
                    "route": {"resource_id": rid, "base_url": BASE_URL, "detail_url": detail_url, "documents_url": f"{BASE_URL}/epps/cft/listContractDocuments.do?resourceId={rid}"},
                    "discovered_at": NOW.isoformat(), "fallback_source": "PUBLISHED_NOTICES",
                    "authority_seed": {"authority_id": authority[0], "org_group_id": authority[1]} if authority else None,
                }
                page_rows += 1
            pages += 1; authority_pages += 1
            if oldest_pub and oldest_pub < CUTOFF:
                cutoff_reached = True; authority_cutoff = True; break
            if not trs or page_rows == 0 and page > 1:
                break
        authority_stats.append({"authority": authority, "pages": authority_pages, "cutoff_reached": authority_cutoff})
    rows = write_rows(records)
    warnings.append({"type": "PUBLISHED_NOTICES_RECALL_FALLBACK", "pages": pages, "lookback_days": LOOKBACK_DAYS, "cutoff_reached": cutoff_reached, "detail_calls": detail_calls, "authority_seed_count": len([x for x in authorities if x]), "coverage_credit": False})
    stats = {"source": SOURCE, "base_url": BASE_URL, "listing_contract": "EPPS_PUBLISHED_NOTICES_RECALL_FALLBACK_V2", "current_materialized": len(rows), "raw_materialized": len(rows), "published_fallback_pages": pages, "deadline_parsed": sum(1 for r in rows if r.get("deadline")), "enumeration_exhausted": False, "enumeration_complete": False, "live_candidate_capable": True, "live_coverage_credit_allowed": False, "errors": errors, "warnings": warnings, "authority_stats": authority_stats, "generated_at": NOW.isoformat(), "semantics": "Official Published Notices repairs recall when Current Opportunities is gated or empty. Malta resolves public CfT workspaces from resourceId for authoritative deadlines. Cyprus may use only previously observed official authority/orgGroup pairs. This remains recall reconstruction, never proof of full current-opportunity exhaustion."}
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not rows: raise SystemExit(3)

if __name__ == "__main__": main()
