from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from pipeline.ted_resolver import classify_downstream, collect_urls

TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = [
    "publication-number",
    "publication-date",
    "buyer-country",
    "document-url-lot",
    "document-url-part",
]


def canonical_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def fetch_page(session: requests.Session, body: dict, retries: int = 6) -> dict:
    last = None
    for attempt in range(retries):
        try:
            r = session.post(TED_SEARCH, json=body, timeout=60)
            last = r
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if attempt + 1 < retries:
                    retry_after = r.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else min(30.0, 1.5 * (2**attempt))
                    except Exception:
                        wait = min(30.0, 1.5 * (2**attempt))
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt + 1 >= retries:
                raise
            time.sleep(min(30.0, 1.5 * (2**attempt)))
    if last is not None:
        last.raise_for_status()
    raise RuntimeError("TED request failed")


def rows_with_cumulative(counter: Counter, denominator: int, extra=None):
    out = []
    cumulative = 0
    for rank, (key, count) in enumerate(counter.most_common(), 1):
        cumulative += count
        row = {
            "rank": rank,
            "key": key,
            "notices": count,
            "share_pct": round(100.0 * count / max(1, denominator), 3),
            "cumulative_pct": round(100.0 * cumulative / max(1, denominator), 3),
        }
        if extra:
            row.update(extra(key))
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-notices", type=int, default=2000)
    ap.add_argument("--page-size", type=int, default=250)
    ap.add_argument("--scope", default="ACTIVE")
    ap.add_argument("--query", default="form-type = competition SORT BY publication-date DESC")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    page_size = max(1, min(250, args.page_size))
    max_notices = max(1, min(15000, args.max_notices))

    session = requests.Session()
    session.headers.update(
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Tender-Engine/BT15-Pareto-Audit",
        }
    )

    notices = []
    total_reported = None
    page = 1
    while len(notices) < max_notices:
        limit = min(page_size, max_notices - len(notices))
        body = {
            "query": args.query,
            "fields": FIELDS,
            "page": page,
            "limit": limit,
            "scope": args.scope,
            "checkQuerySyntax": False,
            "paginationMode": "PAGE_NUMBER",
        }
        data = fetch_page(session, body)
        if total_reported is None:
            total_reported = data.get("totalNoticeCount") or data.get("total") or data.get("totalCount")
        batch = data.get("notices") or []
        if not isinstance(batch, list) or not batch:
            break
        notices.extend(batch)
        if len(batch) < limit:
            break
        page += 1

    notices = notices[:max_notices]
    host_notice_counts = Counter()
    host_url_counts = Counter()
    portal_notice_counts = Counter()
    portal_url_counts = Counter()
    country_notice_counts = Counter()
    portal_hosts = defaultdict(Counter)
    host_portals = defaultdict(Counter)
    notices_with_bt15 = 0
    bt15_url_count = 0
    direct_file_urls = 0

    for notice in notices:
        urls = []
        for field in ("document-url-lot", "document-url-part"):
            urls.extend(collect_urls(notice.get(field)))
        urls = list(dict.fromkeys(urls))
        if not urls:
            continue

        notices_with_bt15 += 1
        country_values = notice.get("buyer-country")
        countries = [str(x) for x in (country_values if isinstance(country_values, list) else [country_values]) if x]
        seen_hosts = set()
        seen_portals = set()

        for url in urls:
            host = canonical_host(url)
            if not host:
                continue
            portal, _ = classify_downstream(url)
            portal = portal or "UNCLASSIFIED"
            bt15_url_count += 1
            host_url_counts[host] += 1
            portal_url_counts[portal] += 1
            portal_hosts[portal][host] += 1
            host_portals[host][portal] += 1
            seen_hosts.add(host)
            seen_portals.add(portal)
            if portal == "DIRECT_HTTP":
                direct_file_urls += 1

        for host in seen_hosts:
            host_notice_counts[host] += 1
        for portal in seen_portals:
            portal_notice_counts[portal] += 1
        for country in set(countries):
            country_notice_counts[country] += 1

    host_rows = rows_with_cumulative(
        host_notice_counts,
        notices_with_bt15,
        extra=lambda host: {
            "urls": host_url_counts[host],
            "portal_mix": dict(host_portals[host].most_common()),
        },
    )
    portal_rows = rows_with_cumulative(
        portal_notice_counts,
        notices_with_bt15,
        extra=lambda portal: {
            "urls": portal_url_counts[portal],
            "top_hosts": dict(portal_hosts[portal].most_common(20)),
        },
    )

    fallback_portals = {"TED_PUBLIC_PAGE_FAST", "GENERIC_PUBLIC_PAGE", "UNCLASSIFIED"}
    fallback_notices = set()
    # Notice-level union is approximated conservatively from per-portal counts in the summary below;
    # host detail remains the canonical way to choose adapter families.
    fallback_portal_notice_sum = sum(portal_notice_counts[p] for p in fallback_portals)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": TED_SEARCH,
        "scope": args.scope,
        "query": args.query,
        "requested_max_notices": max_notices,
        "page_size": page_size,
        "total_reported": total_reported,
        "notices_fetched": len(notices),
        "notices_with_bt15": notices_with_bt15,
        "bt15_notice_coverage_pct": round(100.0 * notices_with_bt15 / max(1, len(notices)), 3),
        "bt15_urls": bt15_url_count,
        "direct_file_urls": direct_file_urls,
        "unique_hosts": len(host_notice_counts),
        "unique_portals": len(portal_notice_counts),
        "fallback_portal_notice_occurrences": fallback_portal_notice_sum,
        "top_hosts": host_rows[:100],
        "top_portals": portal_rows[:100],
        "fallback_hosts": [
            row for row in host_rows
            if any(p in fallback_portals for p in row.get("portal_mix", {}))
        ][:100],
        "country_counts_for_bt15_notices": dict(country_notice_counts.most_common()),
        "notes": [
            "Host and portal shares are notice-occurrence shares among notices that expose at least one BT-15 URL.",
            "A notice may expose more than one host/portal, so portal shares are not mutually exclusive.",
            "TED_PUBLIC_PAGE_FAST and GENERIC_PUBLIC_PAGE are generic anonymous-public fallbacks, not necessarily failures.",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"top_hosts", "top_portals", "fallback_hosts"}}, indent=2, ensure_ascii=False))
    print("\nTOP HOSTS")
    for row in host_rows[:20]:
        print(f"{row['rank']:>2}. {row['key']:<45} {row['notices']:>5} {row['share_pct']:>7.3f}% cum={row['cumulative_pct']:>7.3f}%")
    print("\nTOP PORTALS")
    for row in portal_rows[:20]:
        print(f"{row['rank']:>2}. {row['key']:<28} {row['notices']:>5} {row['share_pct']:>7.3f}% cum={row['cumulative_pct']:>7.3f}%")


if __name__ == "__main__":
    main()
