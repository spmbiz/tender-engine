from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/DK_UDBUD_PUBLIC"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://udbud.dk"
SEARCH_API = f"{BASE}/soegning/public/soegeresultat"
NOW = datetime.now(timezone.utc)
PAGE_SIZE = max(10, min(100, int(os.getenv("DK_PAGE_SIZE", "25"))))
MAX_PAGES = max(1, min(200, int(os.getenv("DK_MAX_PAGES", "80"))))
RETRIES = max(1, min(8, int(os.getenv("DK_REQUEST_RETRIES", "4"))))
DELAY = max(0.0, min(3.0, float(os.getenv("DK_PAGE_DELAY_SECONDS", "0.08"))))

S = requests.Session()
S.headers.update({
    "User-Agent": "Tender-Engine/5.1 (+public procurement research)",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": f"{BASE}/soeg",
})


def clean(v):
    return " ".join(str(v or "").split())


def parse_iso(v):
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_publication_date(v):
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%d-%m-%Y").replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return parse_iso(s)


def next_deadline(values):
    seen = []
    for v in values or []:
        dt = parse_iso(v)
        if dt and dt >= NOW:
            seen.append(dt)
    if not seen:
        return None
    return min(seen).isoformat()


def payload(page: int) -> dict:
    return {
        "pagineringDto": {
            "aktuelSide": page,
            "maksElementer": PAGE_SIZE,
            "sorteringFelt": "PUBLIKATION_DATO",
            "retning": "Desc",
        },
        "filterDto": {
            "formularType": ["NATIONALE_UDBUD", "EU_UDBUD"],
            "opgaveType": [],
            "procedureType": [],
            "smvVenligType": [],
        },
        "udbudStatusFilter": "AKTIV",
    }


def fetch_page(page: int, telemetry: list[dict]):
    for attempt in range(1, RETRIES + 1):
        try:
            r = S.post(SEARCH_API, json=payload(page), timeout=45)
            telemetry.append({
                "page": page,
                "attempt": attempt,
                "status": r.status_code,
                "bytes": len(r.content),
                "rate_limited": r.status_code == 429,
            })
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("resultatElementDtoList"), list):
                    return data
            if r.status_code not in (429, 500, 502, 503, 504):
                return None
        except Exception as exc:
            telemetry.append({"page": page, "attempt": attempt, "error": repr(exc)})
        time.sleep(min(8.0, 0.7 * (2 ** (attempt - 1))))
    return None


def normalize(item: dict):
    if not isinstance(item, dict):
        return None
    notice_id = clean(item.get("noticeId"))
    version = clean(item.get("noticeVersion")) or "01"
    publication_number = clean(item.get("noticePublicationNumber"))
    data_da = item.get("dataDa") if isinstance(item.get("dataDa"), dict) else {}
    data_en = item.get("dataEn") if isinstance(item.get("dataEn"), dict) else {}
    data = data_en if clean(data_en.get("titel")) else data_da
    if not notice_id:
        return None

    published = parse_publication_date(data.get("publiceringsdato"))
    tidsfrister = data.get("tidsfrister") if isinstance(data.get("tidsfrister"), list) else []
    deadline = next_deadline(tidsfrister)
    scope = "EU" if publication_number else "NATIONAL"
    query = {
        "noticeId": notice_id,
        "noticeVersion": version,
        "noticePublicationNumber": publication_number,
    }
    detail_url = f"{BASE}/detaljevisning?{urlencode(query)}"
    value = clean(data.get("anslaaetVaerdi")) or None
    currency = clean(data.get("anslaaetVaerdiValuta")) or None
    all_buyers = [clean(x) for x in (data.get("alleOrdregivere") or []) if clean(x)]

    return {
        "candidate_id": f"DK-UDBUD:{notice_id}:{version}",
        "source": "DK_UDBUD_PUBLIC",
        "portal": "DK_UDBUD",
        "notice_id": notice_id,
        "notice_version": version,
        "notice_publication_number": publication_number or None,
        "publication_scope": scope,
        "title": clean(data.get("titel")) or notice_id,
        "buyer": clean(data.get("ordregiver")) or (all_buyers[0] if all_buyers else None),
        "buyer_id": clean(data.get("ordregiverIdDatavasket") or data.get("ordregiverId")) or None,
        "all_buyers": all_buyers,
        "published": published.isoformat() if published else None,
        "deadline": deadline,
        # The national API query itself is explicitly filtered to AKTIV notices.
        "current": True,
        "cpv": clean(data.get("cpvKode")) or None,
        "cpv_label": clean(data.get("cpvTitel")) or None,
        "estimated_value": value,
        "currency": currency,
        "description": clean(data.get("beskrivelse")) or None,
        "form_type": clean(data.get("formulartype")) or None,
        "form_type_code": clean(data.get("formulartypeKode")) or None,
        "notice_subtype": clean(data.get("bkSubType")) or None,
        "notice_subtype_code": clean(data.get("bkSubTypeKode")) or None,
        "is_amendment": bool(data.get("erAendring")),
        "all_deadlines": tidsfrister,
        "notice_url": detail_url,
        "route": {
            "detail_url": detail_url,
            "search_api": SEARCH_API,
            "notice_id": notice_id,
            "notice_version": version,
            "notice_publication_number": publication_number or None,
        },
        "raw_result": item,
        "discovered_at": NOW.isoformat(),
    }


def main():
    telemetry = []
    rows = []
    total_reported = None
    errors = []
    pages = 0

    for page in range(1, MAX_PAGES + 1):
        data = fetch_page(page, telemetry)
        if data is None:
            errors.append({"type": "PAGE_FETCH_FAILED", "page": page})
            break
        items = data.get("resultatElementDtoList") or []
        if total_reported is None:
            try:
                total_reported = int(data.get("totaltAntalResultater"))
            except Exception:
                total_reported = None
        if not items:
            break
        pages += 1
        rows.extend(items)
        if total_reported is not None and len(rows) >= total_reported:
            break
        if len(items) < PAGE_SIZE:
            break
        if DELAY:
            time.sleep(DELAY)

    seen = {}
    for item in rows:
        rec = normalize(item)
        if rec:
            seen[rec["candidate_id"]] = rec
    current = list(seen.values())
    current.sort(key=lambda x: (x.get("published") or "", x.get("candidate_id") or ""), reverse=True)

    for name in ("raw.jsonl", "current.jsonl"):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for rec in current:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    complete = bool(total_reported is not None and len(rows) >= total_reported)
    if total_reported is not None and not complete and not errors:
        errors.append({"type": "INCOMPLETE_ACTIVE_WINDOW", "seen": len(rows), "total_reported": total_reported})

    stats = {
        "source": "DK_UDBUD_PUBLIC",
        "raw_materialized": len(current),
        "current_materialized": len(current),
        "source_items_seen": len(rows),
        "total_reported": total_reported,
        "active_window_complete": complete,
        "pages_fetched": pages,
        "page_size": PAGE_SIZE,
        "title_parsed": sum(bool(x.get("title")) for x in current),
        "buyer_parsed": sum(bool(x.get("buyer")) for x in current),
        "deadline_parsed": sum(bool(x.get("deadline")) for x in current),
        "value_parsed": sum(bool(x.get("estimated_value")) for x in current),
        "national_notices": sum(x.get("publication_scope") == "NATIONAL" for x in current),
        "eu_notices": sum(x.get("publication_scope") == "EU" for x in current),
        "rate_limit_signals": sum(bool(x.get("rate_limited")) for x in telemetry),
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "official_url": f"{BASE}/soeg",
        "public_search_api": SEARCH_API,
        "query_status": "AKTIV",
        "telemetry": telemetry,
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors or not current:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
