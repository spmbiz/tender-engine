from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from pipeline import discover_de_doe_ocds as base
except ModuleNotFoundError:
    import discover_de_doe_ocds as base

MONTH = os.getenv("DE_MONTH", "").strip()
OUT = Path(os.getenv("DISCOVERY_OUT", f"discovery/global/DE_DOE/month-{MONTH or 'unset'}"))
OUT.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    errors = []
    telemetry = {}
    releases = []
    if not MONTH or len(MONTH) != 7 or MONTH[4] != "-":
        errors.append({"type": "INVALID_DE_MONTH", "value": MONTH})
    else:
        try:
            result = base.fetch_month(MONTH)
            releases = result.pop("releases")
            telemetry = result
        except Exception as exc:
            errors.append({"type": "DE_MONTH_FETCH_FAILED", "month": MONTH, "error": repr(exc)})

    release_by_identity = {}
    for release in releases:
        identity = base.publication_identity(release)
        release_by_identity[identity] = release

    records = {}
    normalization_drops = 0
    for release in release_by_identity.values():
        candidate = base.normalize(release, MONTH)
        if not candidate:
            normalization_drops += 1
            continue
        cid = base.clean(candidate.get("candidate_id"))
        if not cid:
            normalization_drops += 1
            continue
        old = records.get(cid)
        if not old or base.clean(candidate.get("published")) >= base.clean(old.get("published")):
            records[cid] = candidate

    raw = sorted(records.values(), key=lambda x: (x.get("deadline") or "9999", x.get("candidate_id") or ""))
    current = [x for x in raw if x.get("current")]
    write_jsonl(OUT / "raw.jsonl", raw)
    write_jsonl(OUT / "current.jsonl", current)

    complete = bool(not errors and telemetry.get("status") == 200 and telemetry.get("month") == MONTH)
    stats = {
        "source": "DE_DOE",
        "portal": "DE_BEKANNTMACHUNGSSERVICE",
        "listing_contract": "DE_DOE_OFFICIAL_MONTHLY_OCDS_SHARD_V1",
        "month": MONTH,
        "source_releases_seen": len(releases),
        "source_publications_unique": len(release_by_identity),
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "normalization_drops": normalization_drops,
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "errors": errors,
        "telemetry": telemetry,
        "generated_at": base.NOW.isoformat(),
        "semantics": "One independently fetched official German Bekanntmachungsservice monthly OCDS ZIP. The shard is complete only when that exact month returns HTTP 200, its ZIP parses fully, and normalization finishes without errors. Cross-month candidate reconciliation is performed only by the downstream merger.",
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not complete:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
