from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import random
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://www.contractsfinder.service.gov.uk/Harvester/Notices/Data/CSV"
GH = "https://api.github.com"
UA = "Tender-Engine/3.2 CircleCI daily CSV harvester"


def sleep_for_rate_limit(attempt: int) -> None:
    # Contracts Finder documents HTTP 403 as its rate-limit response and asks
    # clients to stop requesting for five minutes. Full cooldown is configurable
    # for persistent runs; smoke tests fail closed instead of hammering.
    cooldown = int(os.environ.get("CF_403_COOLDOWN_SECONDS", "300"))
    time.sleep(cooldown + random.uniform(0.0, 2.0) + min(10, attempt))


def fetch_day(session: requests.Session, day, retries: int = 3) -> tuple[bytes | None, dict]:
    url = f"{BASE}/{day.year}/{day.month}/{day.day}"
    info = {"date": day.isoformat(), "url": url, "attempts": 0, "status": None, "bytes": 0}
    for attempt in range(1, retries + 1):
        info["attempts"] = attempt
        r = session.get(url, timeout=90)
        info["status"] = r.status_code
        if r.status_code == 200:
            info["bytes"] = len(r.content)
            return r.content, info
        if r.status_code == 403:
            if os.environ.get("CF_FAIL_FAST_ON_403", "0") == "1":
                info["rate_limited"] = True
                return None, info
            sleep_for_rate_limit(attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(45.0, 1.8 ** attempt + random.uniform(0.1, 0.8)))
            continue
        r.raise_for_status()
    return None, info


def norm_key(row: dict, *suffixes: str):
    for suffix in suffixes:
        suffix = suffix.lower()
        for key, value in row.items():
            if key and key.strip().lower().endswith(suffix) and value not in (None, ""):
                return value.strip() if isinstance(value, str) else value
    return None


def normalize_csv(content: bytes, day) -> list[dict]:
    # The official harvester CSV is flattened OCDS. We preserve the raw CSV as
    # canonical evidence and only map fields that are positively present.
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        ocid = norm_key(row, "releases/0/ocid", "/ocid", "ocid")
        rid = norm_key(row, "releases/0/id", "/id") or ocid
        if not rid:
            continue
        title = norm_key(row, "/tender/title", "tender/title", "/title") or ""
        description = norm_key(row, "/tender/description", "tender/description", "/description") or ""
        buyer = norm_key(row, "/buyer/name", "/buyers/0/name", "/parties/0/name")
        deadline = norm_key(row, "/tender/tenderperiod/enddate", "tenderperiod/enddate", "/enddate")
        value = norm_key(row, "/tender/value/amount", "value/amount")
        currency = norm_key(row, "/tender/value/currency", "value/currency")
        url = norm_key(row, "uri", "/url")
        out.append({
            "candidate_id": f"CF:{ocid or rid}",
            "source": "UK_CONTRACTS_FINDER_DAILY_CSV",
            "portal": "UK_CONTRACTS_FINDER",
            "release_id": rid,
            "ocid": ocid,
            "title": title,
            "description": description,
            "buyer": buyer,
            "deadline": deadline,
            "estimated_value": value,
            "currency": currency,
            "notice_url": url,
            "published_day": day.isoformat(),
            "evidence": "OFFICIAL_DAILY_CSV",
        })
    return out


def github_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def ensure_release(repo: str, token: str, tag: str) -> dict:
    h = github_headers(token)
    rr = requests.get(f"{GH}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
    if rr.status_code == 404:
        payload = {
            "tag_name": tag,
            "target_commitish": "main",
            "name": f"CircleCI Historical Harvest {tag}",
            "body": "Canonical daily Contracts Finder CSV packs produced by CircleCI workers.",
        }
        cr = requests.post(f"{GH}/repos/{repo}/releases", headers=h, json=payload, timeout=30)
        if cr.status_code not in (201, 422):
            raise RuntimeError(f"create release: {cr.status_code} {cr.text[:500]}")
        for _ in range(10):
            rr = requests.get(f"{GH}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
            if rr.status_code == 200:
                break
            time.sleep(0.5)
    rr.raise_for_status()
    return rr.json()


def upload_asset(repo: str, token: str, tag: str, name: str, data: bytes) -> None:
    h = github_headers(token)
    rel = ensure_release(repo, token, tag)
    for asset in rel.get("assets", []):
        if asset.get("name") == name:
            requests.delete(f"{GH}/repos/{repo}/releases/assets/{asset['id']}", headers=h, timeout=30).raise_for_status()
    uh = dict(h)
    uh["Content-Type"] = "application/gzip"
    r = requests.post(rel["upload_url"].split("{")[0], headers=uh, params={"name": name}, data=data, timeout=180)
    if r.status_code != 201:
        raise RuntimeError(f"upload {name}: {r.status_code} {r.text[:500]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--total", type=int, required=True)
    ap.add_argument("--history-days", type=int, default=360)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-days", type=int, default=0, help="0 means all assigned days")
    args = ap.parse_args()

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    out = Path(args.out)
    raw_dir = out / "raw_daily_csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    assigned = [now.date() - timedelta(days=offset) for offset in range(args.index, args.history_days, args.total)]
    if args.max_days > 0:
        assigned = assigned[: args.max_days]

    # Stagger 30 Circle nodes to avoid a synchronized burst at the source edge.
    if args.total > 1:
        time.sleep(min(20.0, args.index * 0.45))

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    records = []
    day_stats = []
    rate_limited = False
    for day in assigned:
        content, info = fetch_day(session, day)
        day_stats.append(info)
        if content is None:
            if info.get("status") == 403:
                rate_limited = True
                break
            continue
        (raw_dir / f"{day.isoformat()}.csv.gz").write_bytes(gzip.compress(content, compresslevel=4))
        records.extend(normalize_csv(content, day))

    seen = set()
    normalized = []
    for rec in records:
        key = (rec.get("ocid") or "", rec.get("release_id") or "")
        if key in seen:
            continue
        seen.add(key)
        normalized.append(rec)
    with (out / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in normalized:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    elapsed = max(0.001, time.monotonic() - started)
    stats = {
        "provider": "circleci",
        "route": "CONTRACTS_FINDER_OFFICIAL_DAILY_CSV",
        "shard": args.index,
        "total_shards": args.total,
        "history_days": args.history_days,
        "days_assigned": len(assigned),
        "days_downloaded": sum(1 for s in day_stats if s.get("status") == 200),
        "rate_limited": rate_limited,
        "normalized_records": len(normalized),
        "elapsed_seconds": round(elapsed, 3),
        "records_per_second": round(len(normalized) / elapsed, 3),
        "day_stats": day_stats,
        "generated_at": now.isoformat(),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    token = os.environ.get("FLEET_GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("FLEET_GITHUB_TOKEN is required for durable CircleCI harvesting")
    repo = os.environ["CIRCLE_PROJECT_USERNAME"] + "/" + os.environ["CIRCLE_PROJECT_REPONAME"]
    source_run = "circle-historical-" + os.environ["CIRCLE_WORKFLOW_ID"]
    tag = "historical-harvest-" + source_run
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=4) as tf:
        tf.add(out, arcname=f"shard-{args.index:02d}")
    upload_asset(repo, token, tag, f"contracts-finder-daily-shard-{args.index:02d}.tar.gz", buf.getvalue())
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
