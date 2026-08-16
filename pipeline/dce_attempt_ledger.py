from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


SOURCE_SCOPED_SKIP = "SOURCE_SCOPED_TERMINAL_SKIP"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(obj)
    return rows


def candidate_id(rec: dict) -> str:
    return str(rec.get("candidate_id") or rec.get("selection_manifest_candidate_id") or "").strip().casefold()


def material_hash(rec: dict) -> str:
    q = rec.get("qwen") if isinstance(rec.get("qwen"), dict) else {}
    return str(
        q.get("material_fields_hash")
        or rec.get("material_fields_hash")
        or rec.get("notice_material_hash")
        or ""
    ).strip().casefold()


def source_run(rec: dict) -> str:
    return str(
        rec.get("wide_read_run_id")
        or rec.get("source_discovery_run")
        or rec.get("source_run_id")
        or rec.get("source_run")
        or ""
    ).strip()


def load_attempt_index(path: Path) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for rec in load_jsonl(path):
        cid = candidate_id(rec)
        if cid:
            idx.setdefault(cid, []).append(rec)
    return idx


def was_attempted(rec: dict, index: dict[str, list[dict]]) -> bool:
    cid = candidate_id(rec)
    if not cid:
        return False
    attempts = index.get(cid) or []
    if not attempts:
        return False

    mh = material_hash(rec)
    sr = source_run(rec)
    for old in attempts:
        old_mh = material_hash(old)
        old_sr = source_run(old)

        # A source-scoped terminal skip only consumes this exact discovery
        # generation. This is used for rows absent from that canonical snapshot
        # (or already present in a legacy exact queue). If a future discovery
        # generation carries the notice, it is allowed back into DCE even when
        # the selection-side material hash happens to be unchanged.
        if str(old.get("attempt_status") or "") == SOURCE_SCOPED_SKIP:
            if sr and old_sr and sr == old_sr:
                return True
            continue

        # Stable material hash is the strongest exact-version identity for real
        # DCE attempts. A notice whose material hash changes is allowed back in.
        if mh and old_mh:
            if mh == old_mh:
                return True
            continue

        # Legacy/no-hash records are versioned by their discovery source run.
        if sr and old_sr and sr == old_sr:
            return True

        # Last-resort exact identity only when neither side carries version data.
        if not mh and not sr and not old_mh and not old_sr:
            return True
    return False


def count_unseen(queue: Path, ledger: Path) -> tuple[int, int]:
    rows = load_jsonl(queue)
    idx = load_attempt_index(ledger)
    unseen = sum(1 for rec in rows if candidate_id(rec) and not was_attempted(rec, idx))
    return unseen, len(rows)


def write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def update_ledger(queue: Path, ledger: Path, dce_run_id: str, source_run_override: str = "") -> dict:
    rows = load_jsonl(queue)
    existing = load_jsonl(ledger)
    idx = load_attempt_index(ledger)
    now = datetime.now(timezone.utc).isoformat()

    added: list[dict] = []
    for rec in rows:
        cid = candidate_id(rec)
        if not cid or was_attempted(rec, idx):
            continue
        q = rec.get("qwen") if isinstance(rec.get("qwen"), dict) else {}
        entry = {
            "candidate_id": str(rec.get("candidate_id") or rec.get("selection_manifest_candidate_id") or "").strip(),
            "material_fields_hash": material_hash(rec) or None,
            "source_run_id": source_run(rec) or source_run_override or None,
            "dce_run_id": str(dce_run_id),
            "attempt_status": "DCE_RUN_SUCCESS_MATERIALIZED",
            "attempted_at_utc": now,
            "title": rec.get("title"),
            "buyer": rec.get("buyer"),
            "provider": rec.get("provider") or rec.get("portal") or rec.get("selection_portal"),
            "qwen_classification": q.get("classification"),
            "qwen_delivery_mode": q.get("delivery_mode"),
        }
        entry = {k: v for k, v in entry.items() if v is not None}
        existing.append(entry)
        idx.setdefault(cid, []).append(entry)
        added.append(entry)

    write_ledger(ledger, existing)
    return {
        "queue_records": len(rows),
        "ledger_records": len(existing),
        "added": len(added),
        "dce_run_id": str(dce_run_id),
        "added_candidate_ids": [x["candidate_id"] for x in added],
    }


def update_terminal_skips(
    selection: Path,
    summary: Path,
    ledger: Path,
    dce_run_id: str,
    source_run_override: str = "",
) -> dict:
    rows = load_jsonl(selection)
    by_id = {candidate_id(r): r for r in rows if candidate_id(r)}
    payload = json.loads(summary.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{summary}: expected JSON object")

    reasons: list[tuple[str, str]] = []
    for cid in payload.get("missing_from_source_snapshot_candidate_ids") or []:
        reasons.append((str(cid), "MISSING_FROM_CANONICAL_SOURCE_SNAPSHOT"))
    for cid in payload.get("excluded_existing_candidate_ids") or []:
        reasons.append((str(cid), "EXCLUDED_EXISTING_EXACT_IDENTITY"))

    existing = load_jsonl(ledger)
    idx = load_attempt_index(ledger)
    now = datetime.now(timezone.utc).isoformat()
    added: list[dict] = []
    unresolved: list[str] = []

    for raw_cid, reason in reasons:
        rec = by_id.get(raw_cid.strip().casefold())
        if rec is None:
            unresolved.append(raw_cid)
            continue
        sr = source_run(rec) or source_run_override
        if not sr:
            unresolved.append(raw_cid)
            continue
        if was_attempted(rec, idx):
            continue
        q = rec.get("qwen") if isinstance(rec.get("qwen"), dict) else {}
        entry = {
            "candidate_id": str(rec.get("candidate_id") or rec.get("selection_manifest_candidate_id") or raw_cid).strip(),
            "material_fields_hash": material_hash(rec) or None,
            "source_run_id": sr,
            "dce_run_id": str(dce_run_id),
            "attempt_status": SOURCE_SCOPED_SKIP,
            "terminal_skip_reason": reason,
            "attempted_at_utc": now,
            "title": rec.get("title"),
            "buyer": rec.get("buyer"),
            "provider": rec.get("provider") or rec.get("portal") or rec.get("selection_portal"),
            "qwen_classification": q.get("classification"),
            "qwen_delivery_mode": q.get("delivery_mode"),
        }
        entry = {k: v for k, v in entry.items() if v is not None}
        existing.append(entry)
        idx.setdefault(candidate_id(entry), []).append(entry)
        added.append(entry)

    if unresolved:
        raise SystemExit(f"terminal skip rows could not be resolved safely: {sorted(unresolved)}")

    write_ledger(ledger, existing)
    return {
        "selection_records": len(rows),
        "terminal_skip_candidates": len(reasons),
        "ledger_records": len(existing),
        "added": len(added),
        "dce_run_id": str(dce_run_id),
        "added_candidate_ids": [x["candidate_id"] for x in added],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Durable exact-version DCE attempt ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    count = sub.add_parser("count")
    count.add_argument("--queue", required=True)
    count.add_argument("--ledger", default="control/dce_attempt_ledger.jsonl")
    count.add_argument("--json", action="store_true")

    update = sub.add_parser("update")
    update.add_argument("--queue", required=True)
    update.add_argument("--ledger", default="control/dce_attempt_ledger.jsonl")
    update.add_argument("--dce-run-id", required=True)
    update.add_argument("--source-run-id", default="")

    skips = sub.add_parser("update-terminal-skips")
    skips.add_argument("--selection", required=True)
    skips.add_argument("--summary", required=True)
    skips.add_argument("--ledger", default="control/dce_attempt_ledger.jsonl")
    skips.add_argument("--dce-run-id", required=True)
    skips.add_argument("--source-run-id", default="")

    args = ap.parse_args()
    if args.cmd == "count":
        unseen, total = count_unseen(Path(args.queue), Path(args.ledger))
        if args.json:
            print(json.dumps({"unseen": unseen, "total": total, "attempted": total - unseen}))
        else:
            print(unseen)
        return

    if args.cmd == "update-terminal-skips":
        result = update_terminal_skips(
            Path(args.selection),
            Path(args.summary),
            Path(args.ledger),
            str(args.dce_run_id),
            str(args.source_run_id or ""),
        )
    else:
        result = update_ledger(
            Path(args.queue),
            Path(args.ledger),
            str(args.dce_run_id),
            str(args.source_run_id or ""),
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
