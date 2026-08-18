from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from pipeline.ted_resolver import collect_urls

TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = [
    "publication-number",
    "publication-date",
    "notice-title",
    "buyer-name",
    "description-proc",
    "document-url-lot",
    "document-url-part",
]

DEFAULT_HOSTS = [
    "platformazakupowa.pl",
    "contrataciondelestado.es",
    "e-licitatie.ro",
    "ezamowienia.gov.pl",
    "dtvp.de",
    "marches-publics.info",
    "subreport.de",
    "viesiejipirkimai.lt",
    "app.eop.bg",
    "publicprocurement.be",
    "eojn.hr",
    "meinauftrag.rib.de",
    "eis.gov.lv",
    "etenders.gov.ie",
    "tendsign.com",
    "evergabe-online.de",
    "marches-publics.gouv.fr",
    "nen.nipez.cz",
    "tarjouspalvelu.fi",
]


def canonical_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def scalar(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("eng", "en", "fra", "fr", "value"):
            if key in value:
                x = scalar(value.get(key))
                if x:
                    return x
        for v in value.values():
            x = scalar(v)
            if x:
                return x
    if isinstance(value, list):
        for v in value:
            x = scalar(v)
            if x:
                return x
    return value


def fetch_page(session: requests.Session, body: dict, retries: int = 6) -> dict:
    for attempt in range(retries):
        try:
            r = session.post(TED_SEARCH, json=body, timeout=60)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if attempt + 1 < retries:
                    raw = r.headers.get("Retry-After")
                    try:
                        wait = float(raw) if raw else min(30.0, 1.5 * (2 ** attempt))
                    except Exception:
                        wait = min(30.0, 1.5 * (2 ** attempt))
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt + 1 >= retries:
                raise
            time.sleep(min(30.0, 1.5 * (2 ** attempt)))
    raise RuntimeError("TED request failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-scan", type=int, default=10000)
    ap.add_argument("--per-host", type=int, default=1)
    ap.add_argument("--hosts", nargs="*", default=DEFAULT_HOSTS)
    args = ap.parse_args()

    targets = [h.lower().removeprefix("www.") for h in args.hosts]
    wanted = {h: [] for h in targets}
    per_host = max(1, args.per_host)
    max_scan = max(250, min(15000, args.max_scan))

    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Tender-Engine/TopHost-DCE-Smoke",
    })

    scanned = 0
    page = 1
    while scanned < max_scan and any(len(v) < per_host for v in wanted.values()):
        limit = min(250, max_scan - scanned)
        body = {
            "query": "form-type = competition SORT BY publication-date DESC",
            "fields": FIELDS,
            "page": page,
            "limit": limit,
            "scope": "ACTIVE",
            "checkQuerySyntax": False,
            "paginationMode": "PAGE_NUMBER",
        }
        data = fetch_page(s, body)
        notices = data.get("notices") or []
        if not notices:
            break
        scanned += len(notices)

        for notice in notices:
            pub = str(scalar(notice.get("publication-number")) or "").strip()
            if not pub:
                continue
            urls = []
            for field in ("document-url-lot", "document-url-part"):
                urls.extend(collect_urls(notice.get(field)))
            urls = list(dict.fromkeys(urls))
            if not urls:
                continue
            by_host = {}
            for u in urls:
                host = canonical_host(u)
                if host in wanted and host not in by_host:
                    by_host[host] = u
            for host, u in by_host.items():
                if len(wanted[host]) >= per_host:
                    continue
                wanted[host].append({
                    "candidate_id": f"TED:{pub}",
                    "portal": "TED",
                    "source": "TED",
                    "publication_number": pub,
                    "title": scalar(notice.get("notice-title")) or "",
                    "buyer": scalar(notice.get("buyer-name")) or "",
                    "description": scalar(notice.get("description-proc")) or "",
                    "notice_url": f"https://ted.europa.eu/en/notice/-/detail/{pub}",
                    "route": {"publication_number": pub},
                    "benchmark_target_host": host,
                    "benchmark_bt15_url": u,
                    "benchmark_publication_date": scalar(notice.get("publication-date")),
                    "status": "QUEUED",
                })
        page += 1
        if len(notices) < limit:
            break

    rows = []
    for host in targets:
        rows.extend(wanted[host])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "targets": targets,
        "found_hosts": {h: len(wanted[h]) for h in targets},
        "missing_hosts": [h for h in targets if not wanted[h]],
        "rows": len(rows),
        "scanned": scanned,
        "queue": str(out),
        "route_recovery_fields": ["title", "buyer", "description"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not rows:
        raise SystemExit("No target-host TED candidates found")


if __name__ == "__main__":
    main()
