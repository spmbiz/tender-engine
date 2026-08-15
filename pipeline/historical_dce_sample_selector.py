#!/usr/bin/env python3
from __future__ import annotations

"""Select a bounded, stratified historical DCE sample for gate-prevalence research.

Input may be canonical historical_tenders.parquet, .csv, or .csv.gz. Parquet is
streamed through DuckDB in batches so the 2M+ row Global Core can be sampled
without duplicating a large CSV export or loading the full table into RAM.

This does NOT download DCEs and does NOT label old notices green. It turns a
canonical historical notice table into an immutable sample manifest that the same
live DCE resolver/gate pipeline can later consume when old public documents remain
available.
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

LEAN_TERMS = {
    "website": 12, "web site": 12, "web portal": 10, "cms": 10,
    "software": 5, "application": 4, "hosting": 7, "maintenance": 4,
    "graphic": 10, "design": 7, "branding": 9, "creative": 8,
    "video": 10, "audiovisual": 9, "animation": 9,
    "marketing": 7, "communications": 6, "social media": 8,
    "content": 7, "editorial": 8, "publication": 5,
    "print": 7, "printing": 8, "brochure": 7,
    "translation": 8, "transcription": 10,
    "data": 4, "automation": 7, "artificial intelligence": 8,
}
LEAN_CPV_DIVISIONS = {"72", "79", "48", "22", "30"}
EXCLUDE_LANES = {"USA", "USA_FEDERAL", "USASPENDING", "AU_AUSTENDER_AWARD_FIRST", "AUSTRALIA_AWARD_FIRST"}


def _open_csv(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")


def _iter_rows(path: Path, batch_size: int = 10_000) -> Iterator[dict]:
    if path.suffix.casefold() == ".parquet":
        try:
            import duckdb
        except ImportError as exc:
            raise SystemExit("duckdb is required for parquet historical sampling") from exc
        con = duckdb.connect(database=":memory:")
        con.execute("PRAGMA threads=4")
        cur = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
        columns = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for values in rows:
                yield dict(zip(columns, values))
        con.close()
        return
    with _open_csv(path) as f:
        yield from csv.DictReader(f)


def _norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _first(row: dict, *keys: str) -> str:
    # Exact-name first, then case-insensitive fallback for cross-source schemas.
    for key in keys:
        if key in row:
            value = _norm(row.get(key))
            if value and value.upper() not in {"UNKNOWN", "NULL", "NONE", "N/A"}:
                return value
    lower = {str(k).casefold(): k for k in row}
    for key in keys:
        actual = lower.get(key.casefold())
        if actual is None:
            continue
        value = _norm(row.get(actual))
        if value and value.upper() not in {"UNKNOWN", "NULL", "NONE", "N/A"}:
            return value
    return ""


def _cpv(row: dict) -> str:
    raw = _first(row, "cpv", "cpv_code", "main_cpv", "classification_id")
    digits = re.sub(r"\D", "", raw)
    return digits[:2] if len(digits) >= 2 else ""


def _score(row: dict) -> tuple[int, list[str]]:
    title = _first(row, "title", "tender_title", "description").casefold()
    score = 0
    reasons: list[str] = []
    for term, pts in LEAN_TERMS.items():
        if term in title:
            score += pts
            reasons.append(f"+{pts}:{term}")
    cpv = _cpv(row)
    if cpv in LEAN_CPV_DIVISIONS:
        score += 5
        reasons.append(f"+5:cpv-{cpv}")
    url = _first(row, "primary_source_url", "source_url", "notice_url", "url")
    if url.startswith(("http://", "https://")):
        score += 4
        reasons.append("+4:source-url")
    buyer = _first(row, "buyer_name", "buyer", "contracting_authority")
    if buyer:
        score += 2
    return score, reasons


def _identity(row: dict) -> str:
    rid = _first(row, "record_id", "source_record_id", "notice_id", "id")
    if rid:
        return rid
    raw = "|".join([
        _first(row, "country", "country_code"),
        _first(row, "buyer_name", "buyer"),
        _first(row, "title"),
        _first(row, "publication_date", "date"),
    ])
    return "hist:" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def _canonical(row: dict, score: int, reasons: list[str]) -> dict:
    country = _first(row, "country", "country_code", "buyer_country").upper()
    buyer = _first(row, "buyer_name", "buyer", "contracting_authority")
    source = _first(row, "source", "lane", "source_name", "portal").upper()
    return {
        "candidate_id": _identity(row),
        "historical": True,
        "source": source,
        "country": country,
        "buyer": buyer,
        "title": _first(row, "title", "tender_title", "description"),
        "cpv_division": _cpv(row),
        "publication_date": _first(row, "publication_date", "date", "notice_date"),
        "award_date": _first(row, "award_date"),
        "primary_source_url": _first(row, "primary_source_url", "source_url", "notice_url", "url"),
        "sample_priority": score,
        "sample_reason": reasons,
        "research_status": "HISTORICAL_DCE_PENDING",
        "final_verdict_allowed": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Canonical historical_tenders.parquet, .csv or .csv.gz")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=10_000)
    ap.add_argument("--min-score", type=int, default=5)
    ap.add_argument("--country-cap-share", type=float, default=0.20)
    ap.add_argument("--buyer-cap", type=int, default=20)
    args = ap.parse_args()

    path = Path(args.input)
    if not path.is_file():
        raise SystemExit(f"missing input: {path}")
    candidates: list[tuple[int, dict]] = []
    raw_rows = excluded_award_first = 0
    for row in _iter_rows(path):
        raw_rows += 1
        source = _first(row, "source", "lane", "source_name", "portal").upper()
        evidence = _first(row, "evidence_grain", "evidence_lane", "grain").casefold()
        if source in EXCLUDE_LANES or "award-first" in evidence or "award_first" in evidence:
            excluded_award_first += 1
            continue
        score, reasons = _score(row)
        if score < args.min_score:
            continue
        rec = _canonical(row, score, reasons)
        if not rec["primary_source_url"]:
            continue
        candidates.append((score, rec))

    candidates.sort(key=lambda x: (-x[0], x[1]["country"], x[1]["candidate_id"]))
    country_cap = max(50, math.ceil(args.limit * args.country_cap_share))
    country_counts: Counter[str] = Counter()
    buyer_counts: Counter[str] = Counter()
    selected: list[dict] = []
    seen: set[str] = set()

    # Round-robin across country×CPV buckets to preserve useful exploration.
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for _, rec in candidates:
        buckets[(rec["country"] or "UNKNOWN", rec["cpv_division"] or "UNKNOWN")].append(rec)
    active = sorted(buckets, key=lambda k: (-buckets[k][0]["sample_priority"], k))
    while active and len(selected) < args.limit:
        next_active = []
        for key in active:
            if len(selected) >= args.limit:
                break
            queue = buckets[key]
            while queue:
                rec = queue.pop(0)
                cid = rec["candidate_id"]
                buyer_key = f"{rec['country']}|{rec['buyer'].casefold()}"
                if cid in seen:
                    continue
                if country_counts[rec["country"]] >= country_cap:
                    continue
                if rec["buyer"] and buyer_counts[buyer_key] >= args.buyer_cap:
                    continue
                seen.add(cid)
                country_counts[rec["country"]] += 1
                if rec["buyer"]:
                    buyer_counts[buyer_key] += 1
                selected.append(rec)
                break
            if queue and country_counts[key[0]] < country_cap:
                next_active.append(key)
        active = next_active

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "contract": "HISTORICAL_DCE_SAMPLE_V1",
        "input_format": path.suffix.casefold().lstrip("."),
        "raw_rows": raw_rows,
        "excluded_award_first": excluded_award_first,
        "eligible_candidates": len(candidates),
        "selected": len(selected),
        "country_cap": country_cap,
        "buyer_cap": args.buyer_cap,
        "countries": dict(country_counts),
        "cpv_divisions": dict(Counter(r["cpv_division"] for r in selected)),
        "final_verdict_allowed": False,
        "purpose": "estimate historical gate prevalence and operational fit; not bid recommendations",
    }
    Path(str(out) + ".summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
