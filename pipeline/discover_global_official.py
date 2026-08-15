from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE = os.getenv("GLOBAL_SOURCE", "").strip().upper()
OUT = Path(os.getenv("DISCOVERY_OUT", f"discovery/global/{SOURCE.lower() or 'unknown'}"))
OUT.mkdir(parents=True, exist_ok=True)
LOOKBACK_DAYS = max(1, int(os.getenv("LOOKBACK_DAYS", "14")))
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(days=LOOKBACK_DAYS)
UA = "Tender-Engine/4.0 (+public procurement research; official feeds only)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*"})


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def parse_dt(v):
    if not v:
        return None
    s = clean(v)
    for candidate in (s, s.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d %b %Y %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def stable_id(prefix, *parts):
    raw = "|".join(clean(x) for x in parts if x not in (None, ""))
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:24]}"


def first_key(row: dict, *names):
    lower = {str(k).lower().replace(" ", "").replace("_", "").replace("-", ""): v for k, v in row.items()}
    for name in names:
        n = name.lower().replace(" ", "").replace("_", "").replace("-", "")
        if n in lower and lower[n] not in (None, ""):
            return lower[n]
    # fuzzy fallback for bilingual/long headers
    for name in names:
        n = name.lower().replace(" ", "").replace("_", "").replace("-", "")
        for k, v in lower.items():
            if n in k and v not in (None, ""):
                return v
    return None


def write_outputs(records, stats_extra=None):
    dedup = {}
    for r in records:
        cid = clean(r.get("candidate_id"))
        if not cid:
            continue
        dedup[cid] = r
    rows = list(dedup.values())
    rows.sort(key=lambda r: (str(r.get("deadline") or "9999"), str(r.get("candidate_id"))))
    current = [r for r in rows if r.get("current", True)]
    for name, data in (("raw.jsonl", rows), ("current.jsonl", current)):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "source": SOURCE,
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "lookback_days": LOOKBACK_DAYS,
        "generated_at": NOW.isoformat(),
        "errors": [],
    }
    if stats_extra:
        stats.update(stats_extra)
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return stats


def get(url, **kwargs):
    last = None
    for attempt in range(4):
        try:
            r = S.get(url, timeout=60, **kwargs)
            last = r
            if r.status_code in (408, 425, 429) or r.status_code >= 500:
                if attempt < 3:
                    wait = min(25, 2 ** attempt)
                    try:
                        wait = max(wait, int(r.headers.get("Retry-After", "0")))
                    except Exception:
                        pass
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            return r
        except Exception:
            if attempt == 3:
                raise
            time.sleep(min(12, 2 ** attempt))
    if last is not None:
        last.raise_for_status()
    raise RuntimeError(f"request failed: {url}")


def canada():
    url = "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"
    r = get(url)
    text = r.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        title = first_key(row, "title-titre", "title", "tendertitle", "noticeTitle")
        buyer = first_key(row, "organizationName-nomOrganisation", "organization", "buyer", "department")
        notice_id = first_key(row, "tenderNoticeIdentifier-identifiantAvisAppelOffres", "noticeId", "tenderid", "solicitationNumber")
        deadline_raw = first_key(row, "tenderClosingDate-dateClotureAppelOffres", "closingDate", "closeDate")
        pub_raw = first_key(row, "publicationDate-datePublication", "publicationDate", "published")
        notice_url = first_key(row, "tenderNoticeURL-urlAvisAppelOffres", "noticeURL", "url")
        desc = first_key(row, "tenderDescription-descriptionAppelOffres", "description")
        value = first_key(row, "tenderValue-valeurAppelOffres", "estimatedValue", "value")
        deadline = parse_dt(deadline_raw)
        pub = parse_dt(pub_raw)
        if pub and pub < CUTOFF and deadline and deadline < NOW:
            continue
        cid = f"CA:{clean(notice_id)}" if notice_id else stable_id("CA", title, buyer, deadline_raw)
        out.append({
            "candidate_id": cid,
            "source": "CA_CANADABUYS",
            "portal": "CA_CANADABUYS",
            "notice_id": clean(notice_id),
            "title": clean(title),
            "buyer": clean(buyer) or None,
            "deadline": deadline.isoformat() if deadline else clean(deadline_raw) or None,
            "published": pub.isoformat() if pub else clean(pub_raw) or None,
            "current": not deadline or deadline >= NOW,
            "notice_url": clean(notice_url) or None,
            "estimated_value": clean(value) or None,
            "currency": "CAD",
            "description": clean(desc),
            "route": {"document_urls": []},
            "discovered_at": NOW.isoformat(),
        })
    return out, {"official_url": url, "rows_seen": len(out)}


def boamp():
    base = "https://www.boamp.fr/api/explore/v2.1/catalog/datasets/boamp/records"
    out = []
    offset = 0
    pages = 0
    reached_old = False
    while pages < 30 and not reached_old:
        params = {"limit": 100, "offset": offset, "order_by": "dateparution desc"}
        data = get(base, params=params).json()
        results = data.get("results") or data.get("records") or []
        if not results:
            break
        pages += 1
        for obj in results:
            row = obj.get("fields") if isinstance(obj, dict) and isinstance(obj.get("fields"), dict) else obj
            if not isinstance(row, dict):
                continue
            pub = parse_dt(row.get("dateparution"))
            if pub and pub < CUTOFF:
                reached_old = True
                continue
            deadline = parse_dt(row.get("datelimitereponse"))
            nature = clean(row.get("nature_categorise_libelle") or row.get("nature_libelle"))
            # Keep opportunities / amendments, skip explicit result notices.
            if "résultat" in nature.lower() or "resultat" in nature.lower():
                continue
            rid = row.get("idweb") or row.get("id") or row.get("contractfolderid")
            title = row.get("objet") or row.get("titre") or ""
            buyer = row.get("nomacheteur")
            url = row.get("url_avis")
            cid = f"FR-BOAMP:{clean(rid)}" if rid else stable_id("FR-BOAMP", title, buyer, row.get("dateparution"))
            out.append({
                "candidate_id": cid,
                "source": "FR_BOAMP",
                "portal": "FR_BOAMP",
                "notice_id": clean(rid),
                "title": clean(title),
                "buyer": clean(buyer) or None,
                "deadline": deadline.isoformat() if deadline else clean(row.get("datelimitereponse")) or None,
                "published": pub.isoformat() if pub else clean(row.get("dateparution")) or None,
                "current": not deadline or deadline >= NOW,
                "notice_url": clean(url) or None,
                "description": clean(row.get("description") or row.get("objet")),
                "procurement_method": clean(row.get("procedure_libelle") or row.get("type_procedure")) or None,
                "route": {"document_urls": []},
                "discovered_at": NOW.isoformat(),
            })
        offset += len(results)
        if len(results) < 100:
            break
    return out, {"official_url": base, "pages": pages}


def austender():
    url = "https://www.tenders.gov.au/public_data/rss/rss.xml"
    r = get(url)
    root = ET.fromstring(r.content)
    out = []
    for item in root.findall(".//item"):
        def txt(tag):
            el = item.find(tag)
            return clean(el.text if el is not None else "")
        title = txt("title")
        link = txt("link")
        desc = txt("description")
        guid = txt("guid") or link
        pub = parse_dt(txt("pubDate"))
        # AusTender documents this feed as current approaches to market.
        out.append({
            "candidate_id": f"AU:{clean(guid)}" if guid else stable_id("AU", title, link),
            "source": "AU_AUSTENDER",
            "portal": "AU_AUSTENDER",
            "notice_id": clean(guid),
            "title": title,
            "buyer": None,
            "deadline": None,
            "published": pub.isoformat() if pub else txt("pubDate") or None,
            "current": True,
            "notice_url": link or None,
            "description": desc,
            "route": {"document_urls": []},
            "discovered_at": NOW.isoformat(),
        })
    return out, {"official_url": url, "items": len(out)}


def gets_nz():
    base = "https://www.gets.govt.nz/ExternalIndex.htm"
    out = []
    pages = 0
    for page in range(1, 21):
        r = get(base, params={"orderBy": "date", "page": page})
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.find_all("tr")
        page_count = 0
        for tr in rows:
            cells = tr.find_all("td")
            if len(cells) < 6:
                continue
            vals = [clean(c.get_text(" ", strip=True)) for c in cells]
            a = tr.find("a", href=True)
            # Current GETS list order: RFx ID, Reference, Title, Tender Type, Close Date, Organisation.
            rfx = vals[0]
            if not re.fullmatch(r"\d{5,}", rfx or ""):
                continue
            title = vals[2]
            close_raw = vals[4]
            buyer = vals[5]
            href = a.get("href") if a else ""
            link = urljoin("https://www.gets.govt.nz/", href) if href else None
            deadline = parse_dt(re.sub(r"\s*\([^)]*UTC[^)]*\)\s*$", "", close_raw))
            out.append({
                "candidate_id": f"NZ-GETS:{rfx}",
                "source": "NZ_GETS",
                "portal": "NZ_GETS",
                "notice_id": rfx,
                "title": title,
                "buyer": buyer or None,
                "deadline": deadline.isoformat() if deadline else close_raw or None,
                "current": not deadline or deadline >= NOW,
                "notice_url": link,
                "procurement_method": vals[3] or None,
                "reference": vals[1] or None,
                "description": "",
                "route": {"document_urls": []},
                "discovered_at": NOW.isoformat(),
            })
            page_count += 1
        pages += 1
        if page_count == 0:
            break
        # GETS has 25 rows/page; stop on final short page.
        if page_count < 25:
            break
    return out, {"official_url": base, "pages": pages}


def iter_ocds_objects(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("releases"), list):
            for r in obj["releases"]:
                if isinstance(r, dict):
                    yield r
        elif any(k in obj for k in ("ocid", "tender", "buyer", "parties")):
            yield obj
        else:
            for v in obj.values():
                yield from iter_ocds_objects(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_ocds_objects(v)


def seao_qc():
    api = "https://www.donneesquebec.ca/recherche/api/3/action/package_show"
    pkg = get(api, params={"id": "systeme-electronique-dappel-doffres-seao"}).json()
    resources = ((pkg.get("result") or {}).get("resources") or [])
    candidates = []
    for res in resources:
        url = clean(res.get("url"))
        name = clean(res.get("name") or res.get("description"))
        fmt = clean(res.get("format")).lower()
        if not url or not (url.lower().endswith(".json") or fmt == "json"):
            continue
        score = 0
        lname = name.lower()
        if "hebdo_" in lname or "weekly" in lname:
            score += 5
        if "cour" in lname or "current" in lname or "encours" in lname:
            score += 8
        modified = parse_dt(res.get("last_modified") or res.get("created"))
        candidates.append((modified or datetime(1970,1,1,tzinfo=timezone.utc), score, url, name))
    candidates.sort(reverse=True)
    picked = candidates[:2]
    out = []
    for modified, _, url, name in picked:
        data = get(url).json()
        for rel in iter_ocds_objects(data):
            tender = rel.get("tender") or {}
            status = clean(tender.get("status") or rel.get("tag"))
            period = tender.get("tenderPeriod") or {}
            deadline = parse_dt(period.get("endDate"))
            pub = parse_dt(rel.get("date") or tender.get("datePublished"))
            parties = rel.get("parties") or []
            buyers = [p.get("name") for p in parties if isinstance(p, dict) and "buyer" in (p.get("roles") or []) and p.get("name")]
            buyer_obj = rel.get("buyer") or {}
            buyer = buyer_obj.get("name") if isinstance(buyer_obj, dict) else None
            rid = rel.get("ocid") or rel.get("id") or tender.get("id")
            title = tender.get("title") or rel.get("title") or ""
            if not rid and not title:
                continue
            docs = [d.get("url") for d in tender.get("documents") or [] if isinstance(d, dict) and d.get("url")]
            current = (not deadline or deadline >= NOW) and status.lower() not in {"complete", "cancelled", "unsuccessful", "withdrawn"}
            out.append({
                "candidate_id": f"QC-SEAO:{clean(rid)}" if rid else stable_id("QC-SEAO", title, buyer or (buyers[0] if buyers else None), deadline),
                "source": "QC_SEAO",
                "portal": "QC_SEAO",
                "notice_id": clean(rid),
                "ocid": clean(rel.get("ocid")) or None,
                "title": clean(title),
                "buyer": clean(buyer or (buyers[0] if buyers else None)) or None,
                "deadline": deadline.isoformat() if deadline else None,
                "published": pub.isoformat() if pub else None,
                "current": current,
                "notice_url": None,
                "estimated_value": (tender.get("value") or {}).get("amount") if isinstance(tender.get("value"), dict) else None,
                "currency": (tender.get("value") or {}).get("currency") if isinstance(tender.get("value"), dict) else "CAD",
                "description": clean(tender.get("description")),
                "procurement_method": tender.get("procurementMethodDetails") or tender.get("procurementMethod"),
                "route": {"document_urls": docs},
                "discovered_at": NOW.isoformat(),
            })
    return out, {"official_api": api, "resources_considered": len(candidates), "resources_picked": [x[3] for x in picked]}


def germany_doe():
    # Official OpenData endpoint published by Datenservice Öffentlicher Einkauf.
    # The API returns bulk notice exports. We probe each recent day and recursively
    # follow machine-readable download URLs exposed by the service. If the service
    # changes its payload shape, telemetry is preserved rather than fabricating rows.
    endpoint = "https://oeffentlichevergabe.de/api/notice-exports"
    out = []
    telemetry = []
    for days_ago in range(min(LOOKBACK_DAYS, 7)):
        day = (NOW - timedelta(days=days_ago)).date().isoformat()
        try:
            r = get(endpoint, params={"pubDay": day})
            ctype = r.headers.get("content-type", "")
            telemetry.append({"day": day, "status": r.status_code, "content_type": ctype, "bytes": len(r.content)})
            if "json" not in ctype.lower():
                continue
            data = r.json()
        except Exception as exc:
            telemetry.append({"day": day, "error": repr(exc)})
            continue
        # Keep direct notice-like objects if returned. Bulk archive URL support can
        # be extended from telemetry without guessing the service contract.
        for obj in iter_ocds_objects(data):
            tender = obj.get("tender") or {}
            rid = obj.get("ocid") or obj.get("id") or tender.get("id")
            title = tender.get("title") or obj.get("title") or ""
            if not rid and not title:
                continue
            period = tender.get("tenderPeriod") or {}
            deadline = parse_dt(period.get("endDate"))
            parties = obj.get("parties") or []
            buyers = [p.get("name") for p in parties if isinstance(p, dict) and "buyer" in (p.get("roles") or []) and p.get("name")]
            out.append({
                "candidate_id": f"DE-DOE:{clean(rid)}" if rid else stable_id("DE-DOE", title, buyers[0] if buyers else None, day),
                "source": "DE_DOE",
                "portal": "DE_DOE",
                "notice_id": clean(rid),
                "ocid": clean(obj.get("ocid")) or None,
                "title": clean(title),
                "buyer": clean(buyers[0] if buyers else None) or None,
                "deadline": deadline.isoformat() if deadline else None,
                "current": not deadline or deadline >= NOW,
                "notice_url": None,
                "description": clean(tender.get("description")),
                "route": {"document_urls": [d.get("url") for d in tender.get("documents") or [] if isinstance(d, dict) and d.get("url")]},
                "discovered_at": NOW.isoformat(),
            })
    return out, {"official_url": endpoint, "probe_telemetry": telemetry}


ADAPTERS = {
    "CA_CANADABUYS": canada,
    "FR_BOAMP": boamp,
    "AU_AUSTENDER": austender,
    "NZ_GETS": gets_nz,
    "QC_SEAO": seao_qc,
    "DE_DOE": germany_doe,
}


def main():
    if SOURCE not in ADAPTERS:
        raise SystemExit(f"Unknown GLOBAL_SOURCE={SOURCE!r}; choose one of {sorted(ADAPTERS)}")
    try:
        records, extra = ADAPTERS[SOURCE]()
        stats = write_outputs(records, extra)
        # A source can be healthy yet temporarily return zero. Preserve that fact.
        if stats.get("errors"):
            raise SystemExit(2)
    except Exception as exc:
        stats = {
            "source": SOURCE,
            "raw_materialized": 0,
            "current_materialized": 0,
            "lookback_days": LOOKBACK_DAYS,
            "generated_at": NOW.isoformat(),
            "errors": [{"error": repr(exc)}],
        }
        (OUT / "raw.jsonl").write_text("", encoding="utf-8")
        (OUT / "current.jsonl").write_text("", encoding="utf-8")
        (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(stats, indent=2, ensure_ascii=False), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
