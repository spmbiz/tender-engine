from __future__ import annotations

import argparse
import json
from pathlib import Path

# These are coverage lanes, not a claim that every procurement authority in a country is exhausted.
# A run may still be useful when partial, but it must not call itself WORLD_COMPLETE unless all
# required lanes materialized cleanly. UNGM is intentionally listed as a required global lane even
# before its public discovery adapter is installed, so the engine cannot overclaim worldwide coverage.
GLOBAL_PACKS = [
    "discovery-ted",
    "discovery-global-ca-canadabuys",
    "discovery-global-fr-boamp",
    "discovery-global-qc-seao",
    "discovery-global-au-austender",
    "discovery-global-nz-gets",
    "discovery-global-de-doe",
    "discovery-global-es-placsp",
    "discovery-global-us-sam-bulk",
    "discovery-global-nl-tenderned-rss",
    "discovery-global-gr-khmdhs",
    "discovery-global-pl-bzp",
    "discovery-global-lv-iub",
    "discovery-global-ch-simap",
    "discovery-global-no-doffin",
    "discovery-global-it-anac-delta",
]
REQUIRED_SHARDED = {
    "contracts_finder": [f"discovery-contracts-finder-{i}" for i in range(8)],
    "ireland_etenders": [f"discovery-ie-{i}" for i in range(10)],
}
EXTERNAL_REQUIRED_LANES = ["UNGM_PUBLIC"]


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def stats_health(pack_dir: Path) -> dict:
    stats_files = sorted(pack_dir.rglob("stats.json"))
    if not stats_files:
        return {"status": "MISSING_STATS", "stats_files": []}
    bad = []
    for path in stats_files:
        obj = load(path)
        if not isinstance(obj, dict):
            bad.append({"path": str(path), "reason": "UNREADABLE_STATS"})
            continue
        if obj.get("errors"):
            bad.append({"path": str(path), "reason": "ERRORS_PRESENT", "value": obj.get("errors")})
        if obj.get("error"):
            bad.append({"path": str(path), "reason": "ERROR_PRESENT", "value": obj.get("error")})
        status = str(obj.get("status") or "").upper()
        if status in {"ERROR", "FAILED", "BLOCKED", "PARTIAL_ERROR"}:
            bad.append({"path": str(path), "reason": f"STATUS_{status}"})
        if obj.get("truncated_by_page_cap"):
            bad.append({"path": str(path), "reason": "TRUNCATED_BY_PAGE_CAP"})
    return {
        "status": "DEGRADED" if bad else "OK",
        "stats_files": [str(x) for x in stats_files],
        "problems": bad,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="discovery-download")
    ap.add_argument("--out", default="merged/source_coverage.json")
    ap.add_argument("--external-present", default="", help="comma-separated externally implemented coverage lanes")
    ap.add_argument("--strict", action="store_true", help="exit nonzero unless all required lanes are clean")
    args = ap.parse_args()

    root = Path(args.root)
    existing_dirs = {p.name: p for p in root.iterdir() if p.is_dir()} if root.exists() else {}
    expected_packs = list(GLOBAL_PACKS)
    for packs in REQUIRED_SHARDED.values():
        expected_packs.extend(packs)

    missing = [name for name in expected_packs if name not in existing_dirs]
    health = {}
    degraded = []
    for name in expected_packs:
        if name not in existing_dirs:
            continue
        h = stats_health(existing_dirs[name])
        health[name] = h
        if h["status"] != "OK":
            degraded.append(name)

    external_present = {x.strip().upper() for x in args.external_present.split(",") if x.strip()}
    external_missing = [x for x in EXTERNAL_REQUIRED_LANES if x.upper() not in external_present]

    clean = not missing and not degraded and not external_missing
    status = "WORLD_COMPLETE" if clean else "PARTIAL_WORLD_COVERAGE"
    payload = {
        "contract": "SOURCE_COVERAGE_GUARD_V1",
        "coverage_status": status,
        "worldwide_claim_allowed": clean,
        "expected_materialized_packs": len(expected_packs),
        "present_materialized_packs": len(expected_packs) - len(missing),
        "missing_packs": missing,
        "degraded_packs": degraded,
        "external_required_lanes": EXTERNAL_REQUIRED_LANES,
        "external_present_lanes": sorted(external_present),
        "external_missing_lanes": external_missing,
        "pack_health": health,
        "semantics": (
            "WORLD_COMPLETE means every configured discovery lane in this engine run materialized cleanly; "
            "it does not mean every procurement authority on Earth was exhaustively enumerated. "
            "PARTIAL_WORLD_COVERAGE remains usable, but reports and prompts must disclose missing/degraded lanes."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.strict and not clean:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
