from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from pipeline.discover_it_anac_pvl import analyse_template, clean, parse_iso
except ModuleNotFoundError:
    from discover_it_anac_pvl import analyse_template, clean, parse_iso

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/IT_ANAC_DELTA"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://pubblicitalegale.anticorruzione.it"
API_URL = BASE + "/api/v0/avvisi"
PORTAL_URL = BASE + "/bandi"
PVL_LAUNCH = date(2024, 1, 2)
NOW = datetime.now(timezone.utc)
MODE = os.getenv("DISCOVERY_MODE", "delta").strip().lower()
DELTA_LOOKBACK_DAYS = max(1, int(os.getenv("ANAC_PVL_DELTA_LOOKBACK_DAYS", "45")))
WINDOW_DAYS = max(1, min(90, int(os.getenv("ANAC_PVL_WINDOW_DAYS", "31"))))
PAGE_SIZE = max(10, min(500, int(os.getenv("ANAC_PVL_PAGE_SIZE", "500"))))
MAX_PAGES_PER_WINDOW = max(1, int(os.getenv("ANAC_PVL_MAX_PAGES_PER_WINDOW", "2000")))
REQUEST_RETRIES = max(1, min(10, int(os.getenv("ANAC_PVL_REQUEST_RETRIES", "6"))))
WORKERS = max(1, min(8, int(os.getenv("ANAC_PVL_WORKERS", "4"))))
QUERY_CODES = os.getenv("ANAC_PVL_CODICE_SCHEDA", "2,4")
UA = "Tender-Engine/7.2 (+official ANAC PVL public bandi API; full-history reconcile)"


def manifest() -> list[tuple[date, date]]:
    final = NOW.date()
    first = PVL_LAUNCH if MODE == "reconcile" else max(PVL_LAUNCH, final - timedelta(days=DELTA_LOOKBACK_DAYS))
    windows: list[tuple[date, date]] = []
    cursor = first
    while cursor <= final:
        end = min(final, cursor + timedelta(days=WINDOW_DAYS - 1))
        windows.append((cursor, end))
        cursor = end + timedelta(days=1)
    return windows


def fetch_page(session: requests.Session, start: date, end: date, page: int) -> tuple[dict[str, Any], str]:
    params = {
        "dataPubblicazioneStart": start.strftime("%d/%m/%Y"),
        "dataPubblicazioneEnd": end.strftime("%d/%m/%Y"),
        "page": page,
        "size": PAGE_SIZE,
        "codiceScheda": QUERY_CODES,
    }
    last_error: Exception | None = None
    for attempt in range(REQUEST_RETRIES):
        try:
            response = session.get(API_URL, params=params, timeout=90)
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
                raise RuntimeError(f"UNEXPECTED_JSON_SHAPE:{type(payload).__name__}")
            return payload, response.url
        except Exception as exc:
            last_error = exc
            if attempt + 1 < REQUEST_RETRIES:
                time.sleep(min(20.0, 1.25 * (2**attempt)))
    raise RuntimeError(f"ANAC_PVL_PAGE_FAILED {start}/{end} page={page}: {last_error!r}")


def harvest_window(start: date, end: date) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})
    items: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    total_pages: int | None = None
    total_elements: int | None = None
    page = 0

    while page < MAX_PAGES_PER_WINDOW:
        payload, url = fetch_page(session, start, end, page)
        content = payload.get("content") or []
        observed_pages = int(payload.get("totalPages") or 0)
        observed_elements = int(payload.get("totalElements") or 0)
        if total_pages is None:
            total_pages = observed_pages
            total_elements = observed_elements
        elif observed_pages != total_pages or observed_elements != total_elements:
            raise RuntimeError(
                f"ANAC_PVL_TOTAL_DRIFT {start}/{end} page={page} "
                f"pages={observed_pages}/{total_pages} elements={observed_elements}/{total_elements}"
            )
        telemetry.append({
            "page": page,
            "rows": len(content),
            "total_pages": observed_pages,
            "total_elements": observed_elements,
            "last": payload.get("last") is True,
            "request_url": url,
        })
        items.extend(x for x in content if isinstance(x, dict))

        if payload.get("last") is True or page + 1 >= observed_pages:
            break
        if not content:
            raise RuntimeError(f"ANAC_PVL_PREMATURE_EMPTY_PAGE {start}/{end} page={page}")
        page += 1
    else:
        raise RuntimeError(f"ANAC_PVL_HARD_PAGE_CAP {start}/{end} max={MAX_PAGES_PER_WINDOW}")

    if total_elements is not None and len(items) != total_elements:
        raise RuntimeError(
            f"ANAC_PVL_WINDOW_COUNT_MISMATCH {start}/{end}: rows={len(items)} total={total_elements}"
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "items": items,
        "total_elements": total_elements or 0,
        "total_pages": total_pages or 0,
        "pages": telemetry,
        "complete": True,
    }


def normalize(item: dict[str, Any]) -> dict[str, Any] | None:
    notice_id = clean(item.get("idAvviso"))
    if not notice_id or item.get("oscurato") is True:
        return None

    analysed = analyse_template(item)
    published = parse_iso(item.get("dataPubblicazione"))
    deadline = parse_iso(item.get("dataScadenza"))
    active_record = item.get("attivo")

    if deadline and deadline >= NOW and active_record is not False:
        current = True
        currentness = "ANAC_PVL_FULL_HISTORY_FUTURE_DEADLINE_ACTIVE_RECORD"
    elif deadline and deadline < NOW:
        current = False
        currentness = "ANAC_PVL_DEADLINE_EXPIRED"
    elif active_record is False:
        current = False
        currentness = "ANAC_PVL_RECORD_NOT_ACTIVE"
    else:
        current = False
        currentness = "ANAC_PVL_DEADLINE_UNKNOWN_RADAR_ONLY"

    id_appalto = clean(item.get("idAppalto")) or None
    notice_url = f"{BASE}/bandi/{notice_id}?ricercaArchivio=false"
    return {
        "candidate_id": f"IT-PVL:{notice_id}",
        "source": "IT_ANAC_PVL",
        "portal": "ANAC_PVL",
        "grain": "NOTICE_FIRST_TENDER",
        "notice_id": notice_id,
        "procedure_id": id_appalto,
        "id_appalto": id_appalto,
        "ted_publication_number": analysed["ted_publication_number"],
        "title": analysed["title"],
        "buyer": analysed["buyer"],
        "buyers": analysed["buyers"],
        "country": "IT",
        "deadline": deadline.isoformat() if deadline else None,
        "published": published.isoformat() if published else None,
        "current": current,
        "currentness_evidence": currentness,
        "notice_type": clean(item.get("tipologia")) or None,
        "pvl_record_type": clean(item.get("tipo")) or None,
        "codice_scheda": clean(item.get("codiceScheda")) or None,
        "codice_eform": clean(item.get("codiceEform")) or None,
        "active_record": active_record,
        "notice_url": notice_url,
        "description": analysed["description"],
        "cpv": analysed["cpv"],
        "cigs": analysed["cigs"],
        "nature": analysed["nature"],
        "estimated_value": analysed["estimated_value"],
        "currency": "EUR",
        "lot_count": analysed["lot_count"],
        "award_criteria": analysed["award_criteria"],
        "procedure": analysed["procedures"],
        "route": {
            "pvl_notice_id": notice_id,
            "id_appalto": id_appalto,
            "document_urls": analysed["document_urls"],
            "ted_url": analysed["ted_url"],
            "ted_publication_number": analysed["ted_publication_number"],
            "api_url": API_URL,
        },
        "discovered_at": NOW.isoformat(),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    windows = manifest()
    expected = {(a.isoformat(), b.isoformat()) for a, b in windows}
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    source_items: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(harvest_window, start, end): (start, end) for start, end in windows}
        for future in as_completed(futures):
            start, end = futures[future]
            try:
                result = future.result()
                items = result.pop("items")
                source_items.extend(items)
                telemetry.append(result)
            except Exception as exc:
                errors.append({"start": start.isoformat(), "end": end.isoformat(), "error": repr(exc)})

    telemetry.sort(key=lambda x: x.get("start") or "")
    complete_windows = {(x.get("start"), x.get("end")) for x in telemetry if x.get("complete") is True}
    publication_window_complete = bool(not errors and complete_windows == expected)

    rows_by_id: dict[str, dict[str, Any]] = {}
    obscured_or_invalid = 0
    for item in source_items:
        row = normalize(item)
        if not row:
            obscured_or_invalid += 1
            continue
        cid = row["candidate_id"]
        old = rows_by_id.get(cid)
        if not old or str(row.get("published") or "") >= str(old.get("published") or ""):
            rows_by_id[cid] = row

    raw = sorted(rows_by_id.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in raw if x.get("current")]
    radar_unknown = [x for x in raw if x.get("currentness_evidence") == "ANAC_PVL_DEADLINE_UNKNOWN_RADAR_ONLY"]
    write_jsonl(OUT / "raw.jsonl", raw)
    write_jsonl(OUT / "current.jsonl", current)
    write_jsonl(OUT / "radar_unknown_deadline.jsonl", radar_unknown)

    full_history = bool(MODE == "reconcile" and windows and windows[0][0] == PVL_LAUNCH and windows[-1][1] == NOW.date())
    exhaustive = bool(full_history and publication_window_complete)
    stats = {
        "source": "IT_ANAC_PVL",
        "portal": "ANAC_PVL",
        "listing_contract": "ANAC_PVL_BANDI_FULL_PUBLICATION_HISTORY_V4",
        "discovery_mode": MODE,
        "pvl_launch_date": PVL_LAUNCH.isoformat(),
        "query_codes": QUERY_CODES,
        "window_days": WINDOW_DAYS,
        "page_size": PAGE_SIZE,
        "windows_expected": len(windows),
        "windows_completed": len(complete_windows),
        "api_elements_seen": len(source_items),
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "deadline_unknown_radar": len(radar_unknown),
        "obscured_or_invalid_dropped": obscured_or_invalid,
        "with_document_urls": sum(bool((x.get("route") or {}).get("document_urls")) for x in current),
        "with_ted_link": sum(bool((x.get("route") or {}).get("ted_url")) for x in current),
        "full_publication_history_requested": full_history,
        "publication_window_enumeration_complete": publication_window_complete,
        "enumeration_exhausted": exhaustive,
        "enumeration_complete": exhaustive,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": exhaustive and bool(current),
        "errors": errors,
        "warnings": ([] if exhaustive else [{
            "type": "ANAC_PVL_DELTA_OR_INCOMPLETE_FULL_HISTORY",
            "impact": "NO_FULL_LIVE_COVERAGE_CREDIT",
        }]),
        "telemetry": telemetry,
        "generated_at": NOW.isoformat(),
        "source_url": PORTAL_URL,
        "api_url": API_URL,
        "semantics": (
            "Official public ANAC Legal Advertising /bandi JSON API only. In RECONCILE mode every publication-date partition from the PVL service launch (2024-01-02) through today is exhausted and count-reconciled to the API's totalElements. "
            "The live candidate set is then the exact subset with a future dataScadenza and an active record; expired, inactive, obscured and deadline-unknown records cannot be promoted to current. "
            "Deadline-unknown publications are preserved separately as radar. DELTA mode intentionally covers only recent publications and receives no full-history coverage credit."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors or not raw:
        raise SystemExit(3 if errors else 2)
    if MODE == "reconcile" and not exhaustive:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
