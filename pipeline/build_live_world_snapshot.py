#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID_KEYS = ("candidate_id", "canonical_key", "id", "notice_id", "tender_id", "ocid", "reference", "identifier")
TITLE_KEYS = ("title", "name", "tender_title", "notice_title", "description_title")
BUYER_KEYS = ("buyer", "buyer_name", "authority", "contracting_authority", "organisation", "organization")
COUNTRY_KEYS = ("country", "country_code", "buyer_country", "jurisdiction")
SOURCE_KEYS = ("source", "source_name", "portal", "source_family")
DEADLINE_KEYS = ("deadline", "submission_deadline", "closing_date", "close_date", "tender_deadline", "deadline_at")
PUBLICATION_KEYS = ("publication_date", "published_at", "published", "notice_date", "date")
VALUE_KEYS = ("estimated_value", "value", "budget", "amount", "contract_value", "value_amount")
CURRENCY_KEYS = ("currency", "value_currency", "estimated_value_currency")
PROCEDURE_KEYS = ("procedure", "procedure_type", "procurement_method", "method")
CPV_KEYS = ("cpv", "cpv_codes", "classification", "classifications", "category", "categories")
DESCRIPTION_KEYS = (
    "description", "summary", "scope", "object", "short_description", "notice_description",
    "description_text", "contract_description", "additional_information", "details"
)
URL_KEYS = (
    "url", "notice_url", "tender_url", "source_url", "publication_url", "documents_url",
    "document_url", "dce_url", "buyer_url", "links", "attachments", "documents"
)


def first(rec: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = rec.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def clean_text(value: Any, limit: int = 12000) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = str(value)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def collect_description(rec: dict[str, Any]) -> str | None:
    parts: list[str] = []
    seen: set[str] = set()
    for key in DESCRIPTION_KEYS:
        text = clean_text(rec.get(key), 8000)
        if not text:
            continue
        norm = text.casefold()
        if norm in seen:
            continue
        seen.add(norm)
        parts.append(text)
        if sum(len(x) for x in parts) >= 12000:
            break
    if not parts:
        return None
    return " | ".join(parts)[:12000]


def collect_urls(value: Any, out: list[str], seen: set[str], depth: int = 0) -> None:
    if depth > 5 or len(out) >= 16:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in URL_KEYS or isinstance(item, (dict, list)):
                collect_urls(item, out, seen, depth + 1)
    elif isinstance(value, list):
        for item in value:
            collect_urls(item, out, seen, depth + 1)
    elif isinstance(value, str):
        for url in re.findall(r"https?://[^\s\]\[<>\"']+", value):
            url = url.rstrip(".,;)")
            if url not in seen:
                seen.add(url)
                out.append(url)
                if len(out) >= 16:
                    return


def parse_dt(value: Any) -> datetime | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    candidates = [text]
    m = re.search(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+)?", text)
    if m and m.group(0) not in candidates:
        candidates.append(m.group(0))
    for item in candidates:
        try:
            dt = datetime.fromisoformat(item)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(item[:10], fmt).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def source_family(rec: dict[str, Any], cid: str) -> str:
    raw = str(first(rec, SOURCE_KEYS) or "").upper()
    c = cid.upper()
    prefixes = (
        ("TED:", "TED"), ("IE:", "IE"), ("CF:", "UK"), ("UK:", "UK"),
        ("FR:", "FR"), ("DE:", "DE"), ("CA:", "CA"), ("QC:", "QC"),
        ("US-SAM:", "US_SAM"), ("AU:", "AU"), ("NZ:", "NZ"),
        ("PL", "PL"), ("DK", "DK"), ("NL", "NL"), ("FI", "FI"),
        ("BE", "BE"), ("LU", "LU"), ("CY", "CY"), ("MT", "MT"),
    )
    for prefix, family in prefixes:
        if c.startswith(prefix):
            return family
    aliases = {
        "CANADABUYS": "CA", "SEAO": "QC", "BOAMP": "FR", "DOE": "DE",
        "CONTRACTS FINDER": "UK", "AUSTENDER": "AU", "GETS": "NZ",
        "SAM": "US_SAM", "TENDERNED": "NL", "UDBUD": "DK", "HILMA": "FI",
    }
    for token, family in aliases.items():
        if token in raw:
            return family
    return raw[:48] or "UNKNOWN"


def scalar_or_compact(value: Any, limit: int = 1600) -> Any:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float, bool)):
        return value
    return clean_text(value, limit)


def make_row(rec: dict[str, Any], now: datetime) -> tuple[dict[str, Any] | None, str]:
    cid = str(first(rec, ID_KEYS) or "").strip()
    if not cid:
        return None, "MISSING_ID"
    deadline_raw = first(rec, DEADLINE_KEYS)
    deadline_dt = parse_dt(deadline_raw)
    if deadline_dt and deadline_dt <= now:
        return None, "EXPIRED"
    open_state = "OPEN_CONFIRMED_BY_DEADLINE" if deadline_dt else "OPEN_UNVERIFIED_NO_PARSEABLE_DEADLINE"

    urls: list[str] = []
    collect_urls(rec, urls, set())
    row = {
        "candidate_id": cid,
        "source_family": source_family(rec, cid),
        "source": scalar_or_compact(first(rec, SOURCE_KEYS), 300),
        "country": scalar_or_compact(first(rec, COUNTRY_KEYS), 120),
        "buyer": scalar_or_compact(first(rec, BUYER_KEYS), 1200),
        "title": scalar_or_compact(first(rec, TITLE_KEYS), 2000),
        "description": collect_description(rec),
        "cpv_or_category": scalar_or_compact(first(rec, CPV_KEYS), 1800),
        "estimated_value": scalar_or_compact(first(rec, VALUE_KEYS), 300),
        "currency": scalar_or_compact(first(rec, CURRENCY_KEYS), 80),
        "publication_date": scalar_or_compact(first(rec, PUBLICATION_KEYS), 200),
        "deadline": scalar_or_compact(deadline_raw, 240),
        "deadline_utc": deadline_dt.isoformat() if deadline_dt else None,
        "open_state": open_state,
        "procedure": scalar_or_compact(first(rec, PROCEDURE_KEYS), 900),
        "lots": scalar_or_compact(rec.get("lots") or rec.get("lot") or rec.get("lot_count"), 1800),
        "notice_eligibility": scalar_or_compact(rec.get("eligibility") or rec.get("selection_criteria") or rec.get("qualification"), 3000),
        "award_criteria": scalar_or_compact(rec.get("award_criteria") or rec.get("award") or rec.get("evaluation_criteria"), 2200),
        "subcontracting": scalar_or_compact(rec.get("subcontracting") or rec.get("subcontractors") or rec.get("consortium"), 1800),
        "urls": urls,
    }
    return row, open_state


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_previous(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-run", required=True)
    ap.add_argument("--packet-size", type=int, default=500)
    ap.add_argument("--previous", help="Previous normalized live snapshot JSONL(.gz), used only as a continuity guard")
    ap.add_argument("--previous-manifest", help="Previous snapshot manifest for provenance")
    ap.add_argument("--source-regression-ratio", type=float, default=0.70)
    ap.add_argument("--source-regression-min-rows", type=int, default=5)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    out = Path(args.out_dir)
    packets = out / "gpt-packets"
    packets.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    raw_count = 0
    rejected = Counter()
    seen_ids: set[str] = set()
    duplicate_ids = 0
    with Path(args.input).open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            raw_count += 1
            try:
                rec = json.loads(line)
            except Exception:
                rejected["MALFORMED_JSON"] += 1
                continue
            if not isinstance(rec, dict):
                rejected["NON_OBJECT"] += 1
                continue
            row, state = make_row(rec, now)
            if row is None:
                rejected[state] += 1
                continue
            cid = row["candidate_id"]
            if cid in seen_ids:
                duplicate_ids += 1
                continue
            seen_ids.add(cid)
            rows.append(row)

    current_materialized_rows = len(rows)
    current_by_source = Counter(str(r.get("source_family") or "UNKNOWN") for r in rows)
    previous_rows: list[dict[str, Any]] = []
    previous_by_source: Counter[str] = Counter()
    previous_source_run: Any = None

    previous_path = Path(args.previous) if args.previous else None
    if previous_path and previous_path.exists() and previous_path.stat().st_size:
        for prev in iter_previous(previous_path):
            cid = str(prev.get("candidate_id") or "").strip()
            if not cid:
                continue
            deadline_dt = parse_dt(prev.get("deadline_utc") or prev.get("deadline"))
            if deadline_dt and deadline_dt <= now:
                continue
            family = str(prev.get("source_family") or source_family(prev, cid) or "UNKNOWN")
            normalized = dict(prev)
            normalized["source_family"] = family
            previous_rows.append(normalized)
            previous_by_source[family] += 1

    if args.previous_manifest:
        try:
            pm = json.loads(Path(args.previous_manifest).read_text(encoding="utf-8"))
            previous_source_run = pm.get("source_discovery_run")
        except Exception:
            previous_source_run = None

    ratio = min(0.99, max(0.05, float(args.source_regression_ratio)))
    min_rows = max(1, int(args.source_regression_min_rows))
    source_regressions: dict[str, dict[str, Any]] = {}
    for family, previous_count in previous_by_source.items():
        current_count = int(current_by_source.get(family, 0))
        if previous_count >= min_rows and current_count < previous_count * ratio:
            source_regressions[family] = {
                "previous_unexpired_or_unknown": previous_count,
                "current_materialized": current_count,
                "ratio": (current_count / previous_count) if previous_count else 0.0,
            }

    carry_forward_reasons: Counter[str] = Counter()
    carried_by_source: Counter[str] = Counter()
    for prev in previous_rows:
        cid = str(prev.get("candidate_id") or "").strip()
        if not cid or cid in seen_ids:
            continue
        family = str(prev.get("source_family") or "UNKNOWN")
        deadline_dt = parse_dt(prev.get("deadline_utc") or prev.get("deadline"))
        if deadline_dt and deadline_dt > now:
            reason = "FUTURE_DEADLINE_NOT_REOBSERVED"
        elif family in source_regressions:
            reason = "SOURCE_REGRESSION_UNKNOWN_DEADLINE"
        else:
            continue
        row = dict(prev)
        row["carried_forward_from_previous_snapshot"] = True
        row["carry_forward_reason"] = reason
        row["carry_forward_previous_source_run"] = previous_source_run
        if deadline_dt:
            row["deadline_utc"] = deadline_dt.isoformat()
            row["open_state"] = "OPEN_CONFIRMED_BY_DEADLINE"
        else:
            row["open_state"] = "OPEN_UNVERIFIED_NO_PARSEABLE_DEADLINE"
        seen_ids.add(cid)
        rows.append(row)
        carry_forward_reasons[reason] += 1
        carried_by_source[family] += 1

    rows.sort(key=lambda r: (r.get("deadline_utc") or "9999", r.get("source_family") or "", r.get("candidate_id") or ""))

    full = out / "live_open_tenders.jsonl"
    with full.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    gz = out / "live_open_tenders.jsonl.gz"
    with full.open("rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)

    packet_names: list[str] = []
    for idx in range(0, len(rows), max(1, args.packet_size)):
        packet_rows = rows[idx: idx + max(1, args.packet_size)]
        name = f"packet-{idx // max(1, args.packet_size):04d}.jsonl"
        packet_names.append(name)
        with (packets / name).open("w", encoding="utf-8") as f:
            for row in packet_rows:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    by_source = Counter(str(r.get("source_family") or "UNKNOWN") for r in rows)
    by_country = Counter(str(r.get("country") or "UNKNOWN") for r in rows)
    by_state = Counter(str(r.get("open_state") or "UNKNOWN") for r in rows)
    manifest = {
        "schema": "LIVE_WORLD_SNAPSHOT_V1",
        "source_discovery_run": int(args.source_run) if str(args.source_run).isdigit() else str(args.source_run),
        "generated_at": now.isoformat(),
        "rule": "Contains every current canonical discovery row not proven expired, plus explicit high-recall carry-forward from the previous snapshot for still-future deadlines and materially regressed source lanes. Carry-forward never upgrades coverage truth or eligibility.",
        "raw_canonical_rows": raw_count,
        "current_materialized_rows": current_materialized_rows,
        "previous_snapshot_rows_considered": len(previous_rows),
        "previous_source_run": previous_source_run,
        "carried_forward_rows": sum(carry_forward_reasons.values()),
        "carry_forward_reasons": dict(carry_forward_reasons),
        "carried_forward_by_source": dict(carried_by_source.most_common()),
        "source_regressions_guarded": source_regressions,
        "snapshot_rows": len(rows),
        "duplicate_candidate_ids_removed": duplicate_ids,
        "rejected": dict(rejected),
        "open_state_counts": dict(by_state),
        "by_source": dict(by_source.most_common()),
        "by_country": dict(by_country.most_common()),
        "packet_size": args.packet_size,
        "packet_count": len(packet_names),
        "packet_files": packet_names,
        "canonical_jsonl": "live_open_tenders.jsonl",
        "canonical_jsonl_gz": "live_open_tenders.jsonl.gz",
        "canonical_jsonl_gz_sha256": sha256(gz),
    }
    (out / "snapshot_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    instructions = f"""# GPT Wide Read — Live World Snapshot\n\nSource discovery run: `{args.source_run}`  \nSnapshot rows: **{len(rows):,}**  \nGenerated: `{now.isoformat()}`\n\n## Objective\nRead the snapshot semantically. Do **not** treat keyword matches or legacy heuristic scores as business truth. Select only opportunities plausibly executable by SPM Business. For SOLO-only mode, reject anything requiring borrowed references, mandatory partner/reseller status, regulated certification, local licensed trade, forced consortium, specialist onsite team, or another entity's capacity.\n\n## Required first-pass output\nFor each tender worth DCE retrieval, return: `candidate_id`, `preliminary_score` (<=89), `reason`, `solo_fit`, and the uncertainty that requires DCE verification. Do not declare FINAL_SUPER_GREEN from notice text.\n\n## DCE request contract\nWrite `control/gpt_dce_request.json` on `main` using:\n\n```json\n{{\n  \"schema\": \"GPT_DCE_REQUEST_V1\",\n  \"source_discovery_run\": {args.source_run},\n  \"wide_read_run_id\": {args.source_run},\n  \"default_preliminary_score\": 84,\n  \"status\": \"DCE_PENDING\",\n  \"mode\": \"SOLO_LEAN\",\n  \"selection_reason\": \"GPT semantic wide-read of the complete live snapshot\",\n  \"candidate_ids\": [\"...\"]\n}}\n```\n\nA push of that file triggers the DCE fanout. DCE retrieval does not imply eligibility. Final 90+/FINAL_SUPER_GREEN still requires authoritative DCE evidence for every mandatory gate.\n"""
    (out / "GPT_WIDE_READ_INSTRUCTIONS.md").write_text(instructions, encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()