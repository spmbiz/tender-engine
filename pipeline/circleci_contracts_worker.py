from __future__ import annotations

import argparse
import io
import json
import os
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://www.contractsfinder.service.gov.uk/"
GH = "https://api.github.com"


def request_json(session, url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=45)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            time.sleep(0.7 * (attempt + 1))
    raise last or RuntimeError("request failed")


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
        for _ in range(6):
            rr = requests.get(f"{GH}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
            if rr.status_code == 200:
                break
            time.sleep(0.5)
    rr.raise_for_status()
    rel = rr.json()
    for a in rel.get("assets", []):
        if a.get("name") == asset_name:
            requests.delete(f"{GH}/repos/{repo}/releases/assets/{a['id']}", headers=h, timeout=30).raise_for_status()
    uh = dict(h)
    uh["Content-Type"] = "application/gzip"
    u = requests.post(rel["upload_url"].split("{")[0], headers=uh, params={"name": asset_name}, data=data, timeout=120)
    if u.status_code != 201:
        raise RuntimeError(f"upload {asset_name}: {u.status_code} {u.text[:500]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--total", type=int, required=True)
    ap.add_argument("--history-days", type=int, default=360)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    span = max(1, (args.history_days + args.total - 1) // args.total)
    end = now - timedelta(days=args.index * span)
    start = max(now - timedelta(days=args.history_days), end - timedelta(days=span))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/3.0 CircleCI public procurement research"})
    limit = 100
    max_pages = 120
    url = BASE + "Published/Notices/OCDS/Search?" + f"publishedFrom={start.isoformat().replace('+00:00','Z')}&publishedTo={end.isoformat().replace('+00:00','Z')}&stages=tender&limit={limit}"
    records = []
    seen = set()
    pages = 0
    errors = []
    for _ in range(max_pages):
        try:
            data = request_json(session, url)
            pages += 1
        except Exception as exc:
            errors.append({"url": url, "error": repr(exc)})
            break
        for rel in data.get("releases") or []:
            rid = rel.get("id") or rel.get("ocid")
            if not rid or rid in seen:
                continue
            seen.add(rid)
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
            docs = [{"title": d.get("title"), "url": d.get("url"), "format": d.get("format"), "description": d.get("description")} for d in tender.get("documents") or [] if d.get("url")]
            value = tender.get("value") or {}
            records.append({
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
            })
        nxt = (data.get("links") or {}).get("next") or data.get("next")
        if not nxt:
            break
        url = urljoin(BASE, nxt)
    for name, rows in (("raw.jsonl", records), ("current.jsonl", [r for r in records if r["current"]])):
        with (out / name).open("w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    stats = {
        "provider": "circleci",
        "source": "UK_CONTRACTS_FINDER",
        "shard": args.index,
        "total_shards": args.total,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "pages": pages,
        "raw": len(records),
        "current": sum(1 for r in records if r["current"]),
        "errors": errors,
        "generated_at": now.isoformat(),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
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
