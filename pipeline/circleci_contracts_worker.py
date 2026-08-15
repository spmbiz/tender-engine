from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import random
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://www.contractsfinder.service.gov.uk/"
GH = "https://api.github.com"
UA = "Tender-Engine/3.1 CircleCI public procurement research"


def _retry_delay(response, attempt: int) -> float:
    if response is not None:
        ra = response.headers.get("Retry-After")
        if ra:
            try:
                return min(120.0, max(0.5, float(ra)))
            except ValueError:
                pass
    return min(45.0, (1.6 ** attempt) + random.uniform(0.15, 0.9))


def request_json(session, url, metrics: dict, retries=5):
    last = None
    for attempt in range(retries):
        response = None
        try:
            response = session.get(url, timeout=45)
            metrics["requests"] += 1
            if response.status_code == 429:
                metrics["rate_limits"] += 1
                last = RuntimeError("HTTP 429")
                time.sleep(_retry_delay(response, attempt + 1))
                continue
            if response.status_code >= 500:
                metrics["server_retries"] += 1
                last = RuntimeError(f"HTTP {response.status_code}")
                time.sleep(_retry_delay(response, attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
            metrics["errors"] += 1
            if attempt + 1 < retries:
                time.sleep(_retry_delay(response, attempt + 1))
    raise last or RuntimeError("request failed")


def release_to_record(rel: dict, now: datetime, start: datetime, end: datetime) -> dict | None:
    rid = rel.get("id") or rel.get("ocid")
    if not rid:
        return None
    tender = rel.get("tender") or {}
    period = tender.get("tenderPeriod") or {}
    deadline_raw = period.get("endDate")
    deadline = None
    if deadline_raw:
        try:
            deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
        except Exception:
            pass
    parties = rel.get("parties") or []
    buyers = [p.get("name") for p in parties if "buyer" in (p.get("roles") or []) and p.get("name")]
    docs = [
        {"title": d.get("title"), "url": d.get("url"), "format": d.get("format"), "description": d.get("description")}
        for d in tender.get("documents") or []
        if d.get("url")
    ]
    value = tender.get("value") or {}
    return {
        "candidate_id": f"CF:{rel.get('ocid') or rid}",
        "source": "UK_CONTRACTS_FINDER",
        "portal": "UK_CONTRACTS_FINDER",
        "release_id": rid,
        "ocid": rel.get("ocid"),
        "title": tender.get("title") or "",
        "buyer": buyers[0] if buyers else None,
        "deadline": deadline.isoformat() if deadline else None,
        "current": not deadline or deadline >= now,
        "notice_url": tender.get("id") if str(tender.get("id") or "").startswith("http") else None,
        "estimated_value": value.get("amount"),
        "currency": value.get("currency"),
        "description": tender.get("description") or "",
        "procurement_method": tender.get("procurementMethod"),
        "procurement_method_details": tender.get("procurementMethodDetails"),
        "suitability": tender.get("suitability") or {},
        "documents": docs,
        "route": {"document_urls": [d["url"] for d in docs]},
        "published_window_start": start.isoformat(),
        "published_window_end": end.isoformat(),
        "discovered_at": now.isoformat(),
    }


def harvest_window(start: datetime, end: datetime, now: datetime, limit: int, max_pages: int) -> tuple[list[dict], dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    metrics = {"requests": 0, "rate_limits": 0, "server_retries": 0, "errors": 0, "pages": 0}
    url = BASE + "Published/Notices/OCDS/Search?" + (
        f"publishedFrom={start.isoformat().replace('+00:00','Z')}"
        f"&publishedTo={end.isoformat().replace('+00:00','Z')}"
        f"&stages=tender&limit={limit}"
    )
    records: list[dict] = []
    seen: set[str] = set()
    errors: list[dict] = []
    for _ in range(max_pages):
        try:
            data = request_json(session, url, metrics)
            metrics["pages"] += 1
        except Exception as exc:
            errors.append({"url": url, "error": repr(exc)})
            break
        for rel in data.get("releases") or []:
            rec = release_to_record(rel, now, start, end)
            if not rec:
                continue
            rid = rec["release_id"]
            if rid in seen:
                continue
            seen.add(rid)
            records.append(rec)
        nxt = (data.get("links") or {}).get("next") or data.get("next")
        if not nxt:
            break
        url = urljoin(BASE, nxt)
    metrics["records"] = len(records)
    metrics["window_start"] = start.isoformat()
    metrics["window_end"] = end.isoformat()
    metrics["terminal_errors"] = errors
    return records, metrics


def split_window(start: datetime, end: datetime, parts: int) -> list[tuple[datetime, datetime]]:
    parts = max(1, parts)
    total = max(1.0, (end - start).total_seconds())
    step = total / parts
    windows = []
    for i in range(parts):
        a = start + timedelta(seconds=step * i)
        b = end if i == parts - 1 else start + timedelta(seconds=step * (i + 1))
        windows.append((a, b))
    return windows


def upload_release_asset(repo: str, token: str, tag: str, asset_name: str, data: bytes):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    rr = requests.get(f"{GH}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
    if rr.status_code == 404:
        payload = {
            "tag_name": tag,
            "target_commitish": "main",
            "name": f"CircleCI Discovery {tag}",
            "body": "Canonical durable source packs produced by CircleCI workers. Worker artifacts are not the canonical store.",
        }
        cr = requests.post(f"{GH}/repos/{repo}/releases", headers=h, json=payload, timeout=30)
        if cr.status_code not in (201, 422):
            raise RuntimeError(f"create release: {cr.status_code} {cr.text[:500]}")
        for _ in range(8):
            rr = requests.get(f"{GH}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
            if rr.status_code == 200:
                break
            time.sleep(0.5)
    rr.raise_for_status()
    rel = rr.json()
    for asset in rel.get("assets", []):
        if asset.get("name") == asset_name:
            requests.delete(f"{GH}/repos/{repo}/releases/assets/{asset['id']}", headers=h, timeout=30).raise_for_status()
    uh = dict(h)
    uh["Content-Type"] = "application/gzip"
    upload_url = rel["upload_url"].split("{")[0]
    for attempt in range(4):
        u = requests.post(upload_url, headers=uh, params={"name": asset_name}, data=data, timeout=180)
        if u.status_code == 201:
            return
        if u.status_code in (429, 500, 502, 503, 504):
            time.sleep(_retry_delay(u, attempt + 1))
            continue
        raise RuntimeError(f"upload {asset_name}: {u.status_code} {u.text[:500]}")
    raise RuntimeError(f"upload {asset_name} failed after retries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--total", type=int, required=True)
    ap.add_argument("--history-days", type=int, default=360)
    ap.add_argument("--out", required=True)
    ap.add_argument("--io-workers", type=int, default=int(os.environ.get("CIRCLE_IO_WORKERS", "2")))
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=120)
    args = ap.parse_args()

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    span = max(1, (args.history_days + args.total - 1) // args.total)
    end = now - timedelta(days=args.index * span)
    start = max(now - timedelta(days=args.history_days), end - timedelta(days=span))
    io_workers = max(1, min(6, args.io_workers))
    windows = split_window(start, end, io_workers)

    all_records: list[dict] = []
    substats: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="cf-io") as pool:
        futures = [pool.submit(harvest_window, a, b, now, args.limit, args.max_pages) for a, b in windows]
        for future in concurrent.futures.as_completed(futures):
            rows, metrics = future.result()
            all_records.extend(rows)
            substats.append(metrics)

    dedup: dict[str, dict] = {}
    for rec in all_records:
        dedup.setdefault(rec["release_id"], rec)
    records = list(dedup.values())
    records.sort(key=lambda r: (r.get("candidate_id") or ""))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    current = [r for r in records if r["current"]]
    for name, rows in (("raw.jsonl", records), ("current.jsonl", current)):
        with (out / name).open("w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    elapsed = max(0.001, time.monotonic() - started)
    stats = {
        "provider": "circleci",
        "source": "UK_CONTRACTS_FINDER",
        "shard": args.index,
        "total_shards": args.total,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "io_workers": io_workers,
        "subwindows": len(windows),
        "pages": sum(s["pages"] for s in substats),
        "requests": sum(s["requests"] for s in substats),
        "rate_limits": sum(s["rate_limits"] for s in substats),
        "server_retries": sum(s["server_retries"] for s in substats),
        "request_errors": sum(s["errors"] for s in substats),
        "raw_before_dedupe": len(all_records),
        "raw": len(records),
        "current": len(current),
        "elapsed_seconds": round(elapsed, 3),
        "records_per_second": round(len(records) / elapsed, 3),
        "subwindow_stats": substats,
        "generated_at": now.isoformat(),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=5) as tf:
        for p in out.rglob("*"):
            if p.is_file():
                tf.add(p, arcname=p.relative_to(out))

    repo = os.environ["CIRCLE_PROJECT_USERNAME"] + "/" + os.environ["CIRCLE_PROJECT_REPONAME"]
    token = os.environ.get("FLEET_GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("FLEET_GITHUB_TOKEN is required for durable CircleCI harvesting")
    source_run = "circle-" + os.environ["CIRCLE_WORKFLOW_ID"]
    tag = "discovery-harvest-" + source_run
    asset = f"discovery-contracts-finder-circle-{args.index:02d}.tar.gz"
    upload_release_asset(repo, token, tag, asset, buf.getvalue())
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
