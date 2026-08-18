from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/IT_ANAC_DELTA"))
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc)
API = "https://dati.anticorruzione.it/opendata/api/3/action/package_search"
OFFICIAL_PAGE = "https://dati.anticorruzione.it/opendata/dataset"
S = requests.Session()
S.headers.update({"User-Agent": "Tender-Engine/4.7 (+public procurement research)", "Accept": "application/json,*/*"})


def clean(v):
    return " ".join(str(v or "").split())


def base_truth():
    return {
        "source": "IT_ANAC_DELTA",
        "lane": "ARCHIVE_LIFECYCLE_DELTA",
        "live_candidate_capable": False,
        "live_coverage_credit_allowed": False,
        "coverage_semantics": "This ANAC CIG delta adapter is lifecycle/archive intelligence only. It cannot satisfy live-open-tender Italy coverage and must remain a coverage gap until a true current-opportunity source is wired.",
        "official_url": OFFICIAL_PAGE,
        "api_url": API,
    }


def persist_degraded(error_type: str, detail: str, status_code=None):
    (OUT / "current.jsonl").write_text("", encoding="utf-8")
    (OUT / "resource_inventory.json").write_text(
        json.dumps({"resources": [], "degraded": True, "api_url": API}, indent=2), encoding="utf-8"
    )
    err = {"type": error_type, "detail": detail[:700]}
    if status_code is not None:
        err["status_code"] = status_code
    stats = {
        **base_truth(),
        "raw_materialized": 0,
        "current_materialized": 0,
        "degraded": True,
        "generated_at": NOW.isoformat(),
        "errors": [err],
        "note": "Archive/lifecycle intelligence lane only; never promoted into the live open-bid candidate feed.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


def main():
    try:
        r = S.get(API, params={"q": "CIG aggiornamenti delta", "rows": 20}, timeout=90)
        if r.status_code >= 400:
            persist_degraded("API_HTTP_ERROR", f"ANAC CKAN package_search returned HTTP {r.status_code}", r.status_code)
            return
        data = r.json()
    except Exception as exc:
        persist_degraded("API_UNAVAILABLE", repr(exc))
        return

    results = ((data.get("result") or {}).get("results") or [])
    pkg = next(
        (x for x in results if "aggiornamenti delta" in clean(x.get("title")).lower() and clean(x.get("title")).lower().startswith("cig")),
        results[0] if results else None,
    )
    if not pkg:
        persist_degraded("DATASET_NOT_FOUND", "CIG aggiornamenti delta package was not present in the CKAN response")
        return

    resources = [
        {
            "id": x.get("id"),
            "name": x.get("name"),
            "format": x.get("format"),
            "url": x.get("url"),
            "last_modified": x.get("last_modified"),
            "size": x.get("size"),
        }
        for x in (pkg.get("resources") or [])
    ]
    (OUT / "resource_inventory.json").write_text(
        json.dumps(
            {
                "package_id": pkg.get("id"),
                "title": pkg.get("title"),
                "metadata_modified": pkg.get("metadata_modified"),
                "resources": resources,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    csvres = next((x for x in reversed(pkg.get("resources") or []) if clean(x.get("format")).upper() == "CSV" and x.get("url")), None)
    rows = []
    download = {}
    if csvres:
        try:
            rr = S.get(csvres["url"], timeout=180)
            download = {
                "url": csvres["url"],
                "status": rr.status_code,
                "bytes": len(rr.content),
                "content_type": rr.headers.get("content-type"),
            }
            if rr.ok and len(rr.content) <= 300_000_000:
                body = rr.content
                texts = []
                if body[:2] == b"PK":
                    try:
                        z = zipfile.ZipFile(io.BytesIO(body))
                        for name in z.namelist():
                            if name.lower().endswith(".csv"):
                                texts.append(z.read(name).decode("utf-8-sig", errors="replace"))
                    except Exception as exc:
                        download["zip_error"] = repr(exc)
                else:
                    texts = [body.decode("utf-8-sig", errors="replace")]
                for text in texts:
                    sample = text[:10000]
                    delim = ";" if sample.count(";") > sample.count(",") else ","
                    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
                        if row:
                            rows.append(row)
        except Exception as exc:
            download = {"url": csvres.get("url"), "error": repr(exc)}

    with (OUT / "delta_rows.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # This dataset is lifecycle/archive intelligence, never a live open-bid feed.
    (OUT / "current.jsonl").write_text("", encoding="utf-8")
    stats = {
        **base_truth(),
        "raw_materialized": len(rows),
        "current_materialized": 0,
        "degraded": False,
        "generated_at": NOW.isoformat(),
        "errors": [],
        "package_id": pkg.get("id"),
        "package_title": pkg.get("title"),
        "metadata_modified": pkg.get("metadata_modified"),
        "resource_count": len(resources),
        "download": download,
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()