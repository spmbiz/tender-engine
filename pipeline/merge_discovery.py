from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def norm_text(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def exact_record_fingerprint(rec: dict) -> str:
    """Stable exact-content identity for records lacking authoritative IDs.

    This is intentionally *not* a semantic/fuzzy dedupe key. If two records
    differ in any material serialized field they remain separate candidates.
    """
    payload = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_key(rec: dict) -> str:
    cid = norm_text(rec.get("candidate_id"))
    if cid:
        return cid.lower()
    source = norm_text(rec.get("source") or rec.get("portal")).lower()
    rid = norm_text(
        rec.get("resource_id")
        or rec.get("notice_id")
        or rec.get("ocid")
        or rec.get("release_id")
        or rec.get("id")
    ).lower()
    if rid:
        return f"{source}:{rid}"

    # Recall-first rule: never collapse two notices merely because title,
    # buyer and deadline happen to match. Without an authoritative ID we only
    # collapse byte-semantic identical records.
    return f"exact-record:{exact_record_fingerprint(rec)}"


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def load_seen(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    out = set()
    for rec in load_jsonl(path):
        out.add(canonical_key(rec))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="discovery-download")
    ap.add_argument("--out", default="merged")
    ap.add_argument("--seen", default="state/seen_candidates.jsonl")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    seen_index = load_seen(Path(args.seen))

    merged = {}
    source_files = []
    exact_fallback_records = 0
    for path in sorted(root.rglob("*.jsonl")):
        # Raw and current files can overlap. Canonical merge handles exact IDs.
        source_files.append(str(path))
        for rec in load_jsonl(path):
            key = canonical_key(rec)
            if key.startswith("exact-record:"):
                exact_fallback_records += 1
            existing = merged.get(key)
            if existing is None:
                existing = dict(rec)
                existing["canonical_key"] = key
                existing["seen_before"] = key in seen_index
                merged[key] = existing
            else:
                # Prefer non-empty values without destroying richer earlier fields.
                for k, v in rec.items():
                    if existing.get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
                        existing[k] = v
                existing["current"] = bool(existing.get("current") or rec.get("current"))

    rows = list(merged.values())
    rows.sort(key=lambda r: (not bool(r.get("current", True)), str(r.get("deadline") or "9999"), str(r.get("candidate_id") or "")))

    with (out / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    current = [r for r in rows if r.get("current", True)]
    with (out / "current_candidates.jsonl").open("w", encoding="utf-8") as f:
        for rec in current:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    stats = {
        "source_files": source_files,
        "materialized_unique": len(rows),
        "current_unique": len(current),
        "seen_before": sum(1 for r in rows if r.get("seen_before")),
        "records_without_authoritative_id": exact_fallback_records,
        "dedupe_contract": "Authoritative/canonical IDs first; records without IDs dedupe only when their complete normalized JSON is exactly identical. No title/buyer/deadline fuzzy fallback.",
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
