from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from pipeline import discover_de_doe_ocds as base
    from pipeline.github_release_cache import download_asset, extract_tar_gz_bytes, load_json, release_age_seconds, release_by_tag
except ModuleNotFoundError:
    import discover_de_doe_ocds as base
    from github_release_cache import download_asset, extract_tar_gz_bytes, load_json, release_age_seconds, release_by_tag

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/DE_DOE"))
PROOF = Path(os.getenv("DE_DOE_PROOF", "control/de_doe_month_shards_proof.json"))
MAX_AGE_HOURS = max(1.0, float(os.getenv("DE_DOE_CACHE_MAX_AGE_HOURS", "36")))
NOW = datetime.now(timezone.utc)
TERMINAL = {"cancelled", "canceled", "complete", "completed", "withdrawn", "unsuccessful"}


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line:
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_dt(value: Any):
    text = clean(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def refresh_currentness(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    deadline = parse_dt(row.get("deadline"))
    status = clean(row.get("tender_status") or row.get("status")).lower()
    current = bool(deadline and deadline.astimezone(timezone.utc) >= NOW and status not in TERMINAL)
    row["current"] = current
    row["currentness_evidence"] = (
        "DE_DOE_PROVEN_BASELINE_OR_DELTA_FUTURE_DEADLINE"
        if current else "DE_DOE_DEADLINE_EXPIRED_UNKNOWN_OR_TERMINAL"
    )
    return row


def month_keys():
    current = (NOW.year, NOW.month)
    if NOW.month == 1:
        previous = (NOW.year - 1, 12)
    else:
        previous = (NOW.year, NOW.month - 1)
    return [f"{previous[0]:04d}-{previous[1]:02d}", f"{current[0]:04d}-{current[1]:02d}"]


def proof_and_baseline():
    proof = load_json(PROOF)
    if proof.get("schema") != "DE_DOE_MONTH_SHARDS_FULL_PROOF_V2" or proof.get("pass") is not True:
        raise RuntimeError("DE_DOE_MONTH_SHARD_PROOF_NOT_GREEN")
    if proof.get("enumeration_complete") is not True or proof.get("live_coverage_credit_allowed") is not True:
        raise RuntimeError("DE_DOE_MONTH_SHARD_PROOF_NOT_COMPLETE")
    if proof.get("months_requested") != proof.get("months_completed"):
        raise RuntimeError("DE_DOE_MONTH_SHARD_PROOF_MONTH_MISMATCH")
    tag = clean(proof.get("release_tag"))
    release = release_by_tag(tag)
    age_seconds = release_age_seconds(release, now=NOW)
    if age_seconds is None:
        raise RuntimeError("DE_DOE_RELEASE_AGE_UNKNOWN")
    if age_seconds > MAX_AGE_HOURS * 3600:
        raise RuntimeError(f"DE_DOE_PROVEN_RELEASE_STALE age_hours={age_seconds/3600:.2f} max={MAX_AGE_HOURS}")
    body = download_asset(release, "de-doe-month-shards-merged.tar.gz")
    temp = Path(tempfile.mkdtemp(prefix="de-doe-proven-"))
    extract_tar_gz_bytes(body, temp)
    stats = load_json(temp / "de-merged" / "stats.json")
    if stats.get("listing_contract") != "DE_DOE_OFFICIAL_MONTHLY_OCDS_SHARDED_V2":
        raise RuntimeError("DE_DOE_CACHED_STATS_CONTRACT_MISMATCH")
    if stats.get("enumeration_complete") is not True or stats.get("live_coverage_credit_allowed") is not True or stats.get("errors"):
        raise RuntimeError("DE_DOE_CACHED_STATS_NOT_COMPLETE")
    rows = list(iter_jsonl(temp / "de-merged" / "raw.jsonl"))
    return proof, release, age_seconds, stats, rows, temp


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    warnings = []
    temp = None
    baseline_rows = []
    proof = {}
    cached_stats = {}
    release = {}
    age_seconds = None
    try:
        proof, release, age_seconds, cached_stats, baseline_rows, temp = proof_and_baseline()
    except Exception as exc:
        errors.append({"stage": "proven_baseline", "error": repr(exc)})

    overlay_rows = []
    overlay_months = month_keys()
    overlay_telemetry = []
    if not errors:
        for month in overlay_months:
            try:
                result = base.fetch_month(month)
                releases = result.pop("releases")
                normalized = 0
                for release_obj in releases:
                    candidate = base.normalize(release_obj, month)
                    if candidate:
                        overlay_rows.append(candidate)
                        normalized += 1
                result["normalized"] = normalized
                overlay_telemetry.append(result)
            except Exception as exc:
                errors.append({"stage": "live_overlay", "month": month, "error": repr(exc)})
                break

    records = {}
    for row in baseline_rows:
        row = refresh_currentness(row)
        cid = clean(row.get("candidate_id"))
        if cid:
            records[cid] = row
    for row in overlay_rows:
        row = refresh_currentness(row)
        cid = clean(row.get("candidate_id"))
        if not cid:
            continue
        old = records.get(cid)
        if old is None or clean(row.get("published")) >= clean(old.get("published")):
            records[cid] = row

    rows = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x.get("candidate_id") or ""))
    current = [row for row in rows if row.get("current")]
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)

    complete = bool(not errors and baseline_rows and len(overlay_telemetry) == len(overlay_months))
    stats = {
        "source": "DE_DOE",
        "portal": "DE_BEKANNTMACHUNGSSERVICE",
        "listing_contract": "DE_DOE_PROVEN_FULL_BASELINE_PLUS_LIVE_MONTH_DELTA_V3",
        "baseline_release_tag": proof.get("release_tag"),
        "baseline_release_published_at": release.get("published_at") if isinstance(release, dict) else None,
        "baseline_age_hours": round(age_seconds / 3600, 3) if age_seconds is not None else None,
        "baseline_max_age_hours": MAX_AGE_HOURS,
        "baseline_months_requested": cached_stats.get("months_requested"),
        "baseline_months_completed": cached_stats.get("months_completed"),
        "overlay_months": overlay_months,
        "overlay_months_completed": [x.get("month") for x in overlay_telemetry],
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": complete and bool(current),
        "errors": errors,
        "warnings": warnings,
        "overlay_telemetry": overlay_telemetry,
        "generated_at": NOW.isoformat(),
        "semantics": (
            "Production Germany lane combines a recently proven exact full-history monthly OCDS baseline with fresh re-fetches of the current and previous official monthly packages. "
            "The baseline Release must carry a green DE_DOE_MONTH_SHARDS_FULL_PROOF_V2 and be no older than the configured freshness bound. Currentness is recalculated at run time from deadline/status, then recent official releases overlay the baseline by deterministic candidate identity and latest published timestamp. "
            "Any stale/missing proof baseline or live overlay failure keeps enumeration and live coverage fail-closed."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if temp:
        shutil.rmtree(temp, ignore_errors=True)
    if not complete:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
