#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            cid = str(rec.get("candidate_id") or rec.get("record_id") or rec.get("notice_id") or "").strip()
            if cid:
                rows[cid] = rec
    return rows


def portal(rec: dict) -> str:
    return str(rec.get("portal") or rec.get("portal_key") or rec.get("source") or "UNKNOWN").upper()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--previous", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    current = load(Path(args.current))
    previous = load(Path(args.previous))
    cur_ids = set(current)
    prev_ids = set(previous)
    new_ids = cur_ids - prev_ids
    retained = cur_ids & prev_ids
    dropped = prev_ids - cur_ids

    cur_by_portal = Counter(portal(r) for r in current.values())
    new_by_portal = Counter(portal(current[cid]) for cid in new_ids)
    prev_by_portal = Counter(portal(r) for r in previous.values())
    all_portals = sorted(set(cur_by_portal) | set(prev_by_portal))
    portal_metrics = {}
    for p in all_portals:
        c = cur_by_portal[p]
        n = new_by_portal[p]
        portal_metrics[p] = {
            "current": c,
            "previous": prev_by_portal[p],
            "new_vs_previous": n,
            "novelty_rate": round(n / c, 6) if c else 0.0,
        }

    result = {
        "contract": "DISCOVERY_NOVELTY_METRICS_V1",
        "current_unique": len(cur_ids),
        "previous_unique": len(prev_ids),
        "new_vs_previous": len(new_ids),
        "retained_from_previous": len(retained),
        "dropped_since_previous": len(dropped),
        "novelty_rate": round(len(new_ids) / max(1, len(cur_ids)), 6),
        "overlap_rate": round(len(retained) / max(1, len(cur_ids)), 6),
        "portals": portal_metrics,
    }
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
