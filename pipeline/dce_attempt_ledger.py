from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


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

        # Stable material hash is the strongest exact-version identity. A notice
        # whose material hash changes is allowed back into the DCE lane.
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
            "attempt_status": "DCE_RUN_SUCCESS_OR_TERMINAL_SKIP",
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

    ledger.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger.with_suffix(ledger.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in existing:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(ledger)

    return {
        "queue_records": len(rows),
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

    args = ap.parse_args()
    if args.cmd == "count":
        unseen, total = count_unseen(Path(args.queue), Path(args.ledger))
        if args.json:
            print(json.dumps({"unseen": unseen, "total": total, "attempted": total - unseen}))
        else:
            print(unseen)
        return

    result = update_ledger(
        Path(args.queue),
        Path(args.ledger),
        str(args.dce_run_id),
        str(args.source_run_id or ""),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
