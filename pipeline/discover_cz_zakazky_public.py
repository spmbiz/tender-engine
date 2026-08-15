from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/CZ_ZAKAZKY_GOV"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://zakazky.gov.cz/"
DAY_API = "https://api.isd.nipez.cz/isd/seznam/zakazek/zakazky-za-24-hodin"
NOW = datetime.now(timezone.utc)
RETRIES = max(1, min(8, int(os.getenv("CZ_REQUEST_RETRIES", "4"))))

S = requests.Session()
S.headers.update({
    "User-Agent": "Tender-Engine/5.2 (+public procurement research)",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://zakazky.gov.cz",
    "Referer": BASE,
})


def clean(v):
    return " ".join(str(v or "").split())


def pdt(v):
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


def fetch():
    telemetry = []
    for attempt in range(1, RETRIES + 1):
        try:
            r = S.get(DAY_API, timeout=45)
            telemetry.append({
                "attempt": attempt,
                "status": r.status_code,
                "bytes": len(r.content),
                "rate_limited": r.status_code == 429,
            })
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("zakazky_za_24_h"), list):
                    return data, telemetry
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except Exception as exc:
            telemetry.append({"attempt": attempt, "error": repr(exc)})
        time.sleep(min(8.0, 0.7 * (2 ** (attempt - 1))))
    return None, telemetry


def normalize(row: dict):
    if not isinstance(row, dict):
        return None
    nipez = clean(row.get("identifikator_NIPEZ") or row.get("identifikator_nipez"))
    if not nipez:
        return None
    published = pdt(row.get("datum_uverejneni_na_zakazky_gov"))
    deadline = pdt(row.get("lhuta_pro_podani"))
    status = clean(row.get("stav"))
    # NIPEZ can expose stale historical deadlines while still marking a row active.
    # A known deadline must therefore be future; status alone is accepted only if no deadline exists.
    current = bool(deadline >= NOW) if deadline else status.upper() == "AKTIVNI_NEUKONCEN"
    return {
        "candidate_id": f"CZ-NIPEZ:{nipez}",
        "source": "CZ_ZAKAZKY_GOV",
        "portal": "CZ_NIPEZ",
        "notice_id": nipez,
        "nipez_id": nipez,
        "title": clean(row.get("nazev_verejne_zakazky")) or nipez,
        "buyer": clean(row.get("nazev_zadavatele")) or None,
        "published": published.isoformat() if published else None,
        "deadline": deadline.isoformat() if deadline else None,
        "current": current,
        "status": status or None,
        "description": clean(row.get("popis_predmetu")) or None,
        "procurement_method": clean(row.get("typ_zadavaciho_postupu")) or None,
        "notice_url": BASE,
        "route": {
            "registry_url": BASE,
            "incremental_api": DAY_API,
            "nipez_id": nipez,
        },
        "raw_notice": row,
        "discovered_at": NOW.isoformat(),
    }


def main():
    data, telemetry = fetch()
    errors = []
    source_rows = []
    reported = None
    if data is None:
        errors.append({"type": "API_FETCH_FAILED"})
    else:
        source_rows = data.get("zakazky_za_24_h") or []
        try:
            reported = int(data.get("pocet_zakazek"))
        except Exception:
            reported = None
        if reported is not None and reported != len(source_rows):
            errors.append({"type": "COUNT_MISMATCH", "reported": reported, "seen": len(source_rows)})

    seen = {}
    for row in source_rows:
        rec = normalize(row)
        if rec:
            seen[rec["candidate_id"]] = rec
    raw = list(seen.values())
    raw.sort(key=lambda x: (x.get("published") or "", x.get("candidate_id") or ""), reverse=True)
    current = [x for x in raw if x.get("current")]

    for name, rows in (("raw.jsonl", raw), ("current.jsonl", current)):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for rec in rows:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    stats = {
        "source": "CZ_ZAKAZKY_GOV",
        "lane": "INCREMENTAL_24H",
        "coverage_semantics": "Official NIPEZ/Zakazky.gov.cz procurement records published during the latest 24-hour feed; not the full active national universe.",
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "source_items_seen": len(source_rows),
        "source_items_reported": reported,
        "title_parsed": sum(bool(x.get("title")) for x in raw),
        "buyer_parsed": sum(bool(x.get("buyer")) for x in raw),
        "published_parsed": sum(bool(x.get("published")) for x in raw),
        "deadline_parsed": sum(bool(x.get("deadline")) for x in raw),
        "stale_deadline_rejected": sum(bool(x.get("deadline")) and not x.get("current") for x in raw),
        "rate_limit_signals": sum(bool(x.get("rate_limited")) for x in telemetry),
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "official_url": BASE,
        "public_incremental_api": DAY_API,
        "telemetry": telemetry,
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors or not raw:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
