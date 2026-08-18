#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "QWEN_AB_GOLDEN_FIXTURE_V2"
DEFAULT_FUTURE_DEADLINE = "2099-09-21T12:00:00+00:00"


def candidate_id(row: dict[str, Any]) -> str:
    n = row.get("notice") if isinstance(row.get("notice"), dict) else row
    return str(row.get("canonical_notice_id") or n.get("candidate_id") or n.get("notice_id") or n.get("id") or "").strip()


def canonical_hash(row: dict[str, Any]) -> str:
    copy = json.loads(json.dumps(row, ensure_ascii=False))
    copy.pop("material_fields_hash", None)
    copy.pop("input_material_fields_hash", None)
    payload = json.dumps(copy, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_deadline(row: dict[str, Any], future: str) -> dict[str, Any]:
    out = json.loads(json.dumps(row, ensure_ascii=False))
    n = out.get("notice") if isinstance(out.get("notice"), dict) else out
    original = n.get("deadline") or n.get("deadline_utc") or out.get("deadline") or out.get("deadline_utc")
    out["ab_fixture_schema"] = SCHEMA
    out["ab_original_deadline"] = original
    out["ab_future_deadline"] = future
    n["ab_original_deadline"] = original
    n["deadline"] = future
    n["deadline_utc"] = future
    if n is not out:
        out["notice"] = n
    out["material_fields_hash"] = canonical_hash(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Materialize a byte-identical, time-stable Qwen A/B golden fixture.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--golden", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--future-deadline", default=DEFAULT_FUTURE_DEADLINE)
    args = ap.parse_args()

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    ids = [str(x["candidate_id"]) for x in golden.get("cases") or []]
    wanted = set(ids)
    found: dict[str, dict[str, Any]] = {}
    with Path(args.source).open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            cid = candidate_id(row)
            if cid in wanted:
                found[cid] = row
    missing = [cid for cid in ids if cid not in found]
    if missing:
        raise SystemExit(f"missing golden candidates: {missing}")

    rows = [normalize_deadline(found[cid], args.future_deadline) for cid in ids]
    out = Path(args.out)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "rows": len(rows),
        "candidate_ids": ids,
        "future_deadline": args.future_deadline,
        "sha256": digest,
        "safety": {
            "fixture_only": True,
            "canonical_source_not_modified": True,
            "original_deadline_preserved": True,
            "same_fixture_for_baseline_and_current": True,
            "production_deadline_logic_not_disabled": True,
        },
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
