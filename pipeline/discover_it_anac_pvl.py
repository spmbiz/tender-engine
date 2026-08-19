from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/IT_ANAC_DELTA"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://pubblicitalegale.anticorruzione.it"
API_URL = BASE + "/api/v0/avvisi"
PORTAL_URL = BASE + "/bandi"
NOW = datetime.now(timezone.utc)
LOOKBACK_DAYS = max(30, int(os.getenv("ANAC_PVL_LOOKBACK_DAYS", "730")))
WINDOW_DAYS = max(1, min(90, int(os.getenv("ANAC_PVL_WINDOW_DAYS", "31"))))
PAGE_SIZE = max(10, min(500, int(os.getenv("ANAC_PVL_PAGE_SIZE", "100"))))
MAX_PAGES_PER_WINDOW = max(1, int(os.getenv("ANAC_PVL_MAX_PAGES_PER_WINDOW", "1000")))
REQUEST_RETRIES = max(1, int(os.getenv("ANAC_PVL_REQUEST_RETRIES", "5")))
PAGE_DELAY = max(0.0, float(os.getenv("ANAC_PVL_PAGE_DELAY_SECONDS", "0.05")))
QUERY_CODES = os.getenv("ANAC_PVL_CODICE_SCHEDA", "2,4")
UA = "Tender-Engine/7.0 (+public procurement research; ANAC PVL public API)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json"})


def clean(value):
    return " ".join(str(value or "").split())


def parse_iso(value):
    text = clean(value)
    if not text:
        return None
    try:
        out = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def preferred_template(item):
    templates = item.get("templates") or []
    for wrapper in templates:
        if isinstance(wrapper, dict) and clean(wrapper.get("lingua")).lower() == "it":
            template = wrapper.get("template")
            if isinstance(template, dict):
                return template
    for wrapper in templates:
        if isinstance(wrapper, dict) and isinstance(wrapper.get("template"), dict):
            return wrapper["template"]
    return {}


def analyse_template(item):
    template = preferred_template(item)
    metadata = template.get("metadata") if isinstance(template.get("metadata"), dict) else {}
    sections = template.get("sections") if isinstance(template.get("sections"), list) else []

    title = clean(metadata.get("titolo"))
    description = clean(metadata.get("descrizione"))
    if not title or title.lower() in {"senza titolo", "untitled", "n/a"}:
        title = description[:1500] or clean(item.get("idAvviso"))
    ted_url = clean(metadata.get("link_eform_ted")) or None

    buyers = []
    document_urls = []
    cpv = []
    cigs = []
    nature = []
    award_criteria = []
    procedures = []
    lot_values = []
    lot_count = 0
    object_descriptions = []

    def add_unique(bucket, value):
        value = clean(value)
        if value and value not in bucket:
            bucket.append(value)

    for section in sections:
        if not isinstance(section, dict):
            continue
        fields = section.get("fields") if isinstance(section.get("fields"), dict) else {}
        subjects = fields.get("soggetti_sa")
        if isinstance(subjects, list):
            for subject in subjects:
                if isinstance(subject, dict):
                    add_unique(buyers, subject.get("denominazione_amministrazione"))
        add_unique(document_urls, fields.get("documenti_di_gara_link"))
        add_unique(procedures, fields.get("tipo_procedura_aggiudicazione"))

        items = section.get("items") if isinstance(section.get("items"), list) else []
        for obj in items:
            if not isinstance(obj, dict):
                continue
            if clean(obj.get("tipo_oggetto")).lower() == "lotto":
                lot_count += 1
            add_unique(cpv, obj.get("cpv"))
            add_unique(cigs, obj.get("cig"))
            add_unique(nature, obj.get("natura_principale"))
            add_unique(award_criteria, obj.get("criteri_aggiudicazione"))
            add_unique(document_urls, obj.get("documenti_di_gara_link"))
            add_unique(object_descriptions, obj.get("descrizione"))
            value = obj.get("valore_complessivo_stimato")
            if isinstance(value, (int, float)) and value >= 0:
                lot_values.append(float(value))

    if ted_url and ted_url in document_urls:
        document_urls.remove(ted_url)

    estimated_value = sum(lot_values) if lot_values else None
    if not description and object_descriptions:
        description = " | ".join(object_descriptions)[:12000]

    return {
        "title": title,
        "description": description,
        "buyer": buyers[0] if buyers else None,
        "buyers": buyers,
        "document_urls": document_urls,
        "ted_url": ted_url,
        "cpv": cpv,
        "cigs": cigs,
        "nature": nature,
        "award_criteria": award_criteria,
        "procedures": procedures,
        "lot_count": lot_count,
        "estimated_value": estimated_value,
    }


def request_page(start: date, end: date, page: int):
    params = {
        "dataPubblicazioneStart": start.strftime("%d/%m/%Y"),
        "dataPubblicazioneEnd": end.strftime("%d/%m/%Y"),
        "page": page,
        "size": PAGE_SIZE,
        "codiceScheda": QUERY_CODES,
    }
    last_error = None
    for attempt in range(REQUEST_RETRIES):
        try:
            response = S.get(API_URL, params=params, timeout=60)
            if response.status_code in (408, 425, 429) or response.status_code >= 500:
                if attempt + 1 < REQUEST_RETRIES:
                    time.sleep(min(12, 2 ** attempt))
                    continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise RuntimeError("ANAC avvisi API returned unexpected JSON shape")
            return data, response.url
        except Exception as exc:
            last_error = exc
            if attempt + 1 < REQUEST_RETRIES:
                time.sleep(min(8, 2 ** attempt))
    raise RuntimeError(f"ANAC avvisi API request failed: {last_error!r}")


def materialize(item):
    if not isinstance(item, dict):
        return None
    notice_id = clean(item.get("idAvviso"))
    if not notice_id:
        return None
    if item.get("oscurato") is True:
        return None

    published = parse_iso(item.get("dataPubblicazione"))
    deadline = parse_iso(item.get("dataScadenza"))
    if deadline and deadline < NOW:
        return None

    analysed = analyse_template(item)
    notice_url = f"{BASE}/bandi/{notice_id}?ricercaArchivio=false"
    id_appalto = clean(item.get("idAppalto")) or None
    currentness = "ANAC_PVL_API_FUTURE_DEADLINE" if deadline else "ANAC_PVL_API_RECENT_BANDO_DEADLINE_UNKNOWN"

    return {
        "candidate_id": f"IT-PVL:{notice_id}",
        "source": "IT_ANAC_PVL",
        "portal": "ANAC_PVL",
        "notice_id": notice_id,
        "id_appalto": id_appalto,
        "title": analysed["title"],
        "buyer": analysed["buyer"],
        "buyers": analysed["buyers"],
        "country": "IT",
        "deadline": deadline.isoformat() if deadline else None,
        "published": published.isoformat() if published else None,
        "current": True,
        "currentness_evidence": currentness,
        "notice_type": clean(item.get("tipologia")) or None,
        "pvl_record_type": clean(item.get("tipo")) or None,
        "codice_scheda": clean(item.get("codiceScheda")) or None,
        "codice_eform": clean(item.get("codiceEform")) or None,
        "active_record": item.get("attivo"),
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
            "api_url": API_URL,
        },
        "discovered_at": NOW.isoformat(),
    }


def write_rows(records):
    rows = sorted(records.values(), key=lambda row: (row.get("deadline") or "9999", row["candidate_id"]))
    for name in ("raw.jsonl", "current.jsonl"):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def write_stats(records, *, windows, pages, api_elements_seen, errors, window_complete):
    rows = write_rows(records)
    stats = {
        "source": "IT_ANAC_PVL",
        "portal": "ANAC_PVL",
        "listing_contract": "ANAC_PVL_OFFICIAL_AVVISI_API_V3",
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "with_deadline": sum(1 for row in rows if row.get("deadline")),
        "deadline_unknown": sum(1 for row in rows if not row.get("deadline")),
        "with_document_urls": sum(1 for row in rows if (row.get("route") or {}).get("document_urls")),
        "with_ted_link": sum(1 for row in rows if (row.get("route") or {}).get("ted_url")),
        "publication_lookback_days": LOOKBACK_DAYS,
        "window_days": WINDOW_DAYS,
        "query_codes": QUERY_CODES,
        "page_size": PAGE_SIZE,
        "windows_fetched": windows,
        "pages_fetched": pages,
        "api_elements_seen": api_elements_seen,
        "publication_window_enumeration_complete": bool(window_complete and not errors),
        "enumeration_exhausted": False,
        "enumeration_complete": False,
        "live_candidate_capable": True,
        "live_coverage_credit_allowed": False,
        "errors": errors,
        "warnings": [
            {
                "type": "ANAC_PVL_BANDI_PUBLICATION_WINDOW_RECALL_ONLY",
                "lookback_days": LOOKBACK_DAYS,
                "query_codes": QUERY_CODES,
                "coverage_credit": False,
                "reason": "Official /bandi UI uses these API filters, but a bounded publication window is not proof of exhaustive current-universe coverage.",
            }
        ],
        "generated_at": NOW.isoformat(),
        "source_url": PORTAL_URL,
        "api_url": API_URL,
        "semantics": "Official ANAC PVL /bandi JSON API. Exact idAvviso is preserved; future dataScadenza proves currentness, while missing deadline stays UNKNOWN. DCE and TED routes are taken directly from the API payload. Coverage remains recall-only until full current-universe semantics are proven.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main():
    records = {}
    errors = []
    pages = 0
    windows = 0
    api_elements_seen = 0
    all_windows_complete = True

    first_day = (NOW - timedelta(days=LOOKBACK_DAYS)).date()
    final_day = NOW.date()
    window_start = first_day

    while window_start <= final_day:
        window_end = min(final_day, window_start + timedelta(days=WINDOW_DAYS - 1))
        windows += 1
        page = 0
        window_finished = False
        while page < MAX_PAGES_PER_WINDOW:
            try:
                payload, request_url = request_page(window_start, window_end, page)
            except Exception as exc:
                errors.append({
                    "type": "ANAC_API_REQUEST_ERROR",
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "page": page,
                    "error": repr(exc),
                })
                all_windows_complete = False
                break

            content = payload.get("content") or []
            pages += 1
            api_elements_seen += len(content)
            for item in content:
                row = materialize(item)
                if row:
                    records[row["candidate_id"]] = row

            # Durable local checkpoint: a runner timeout cannot erase every page
            # already recovered from the official API.
            write_stats(
                records,
                windows=windows,
                pages=pages,
                api_elements_seen=api_elements_seen,
                errors=errors,
                window_complete=False,
            )

            total_pages = payload.get("totalPages")
            is_last = payload.get("last") is True
            if not content or is_last or (isinstance(total_pages, int) and page + 1 >= total_pages):
                window_finished = True
                break

            page += 1
            if PAGE_DELAY:
                time.sleep(PAGE_DELAY)
        else:
            errors.append({
                "type": "ANAC_API_HARD_PAGE_CAP_REACHED",
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "max_pages": MAX_PAGES_PER_WINDOW,
            })
            all_windows_complete = False

        if not window_finished:
            all_windows_complete = False
        window_start = window_end + timedelta(days=1)

    stats = write_stats(
        records,
        windows=windows,
        pages=pages,
        api_elements_seen=api_elements_seen,
        errors=errors,
        window_complete=all_windows_complete,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["current_materialized"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
