from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value
    except Exception:
        return default


def _iter_rows(payload):
    if isinstance(payload, list):
        yield from (x for x in payload if isinstance(x, dict))
        return
    if not isinstance(payload, dict):
        return
    for key in ("review_queue", "pending_final_review", "items", "pending"):
        rows = payload.get(key)
        if isinstance(rows, list):
            yield from (x for x in rows if isinstance(x, dict))


def _is_authenticity_pending(row: dict) -> bool:
    stage = str(row.get("review_stage") or row.get("stage") or row.get("review_lane") or "").upper()
    state = str(row.get("review_state") or row.get("state") or "").upper()
    quality = str(row.get("content_quality") or row.get("evidence_quality") or "").upper()
    gate_ready = row.get("gate_readiness")
    if "DCE_AUTHENTICITY" in stage:
        return True
    if state and state not in {"PENDING_GPT_WEB", "PENDING", "REVIEW_REQUIRED"}:
        return False
    if gate_ready is False and quality in {"UNKNOWN_RETRIEVED_DOCUMENT", "SUBSTANTIVE_DCE_RELEVANCE_UNVERIFIED", "DCE_CONTENT_UNVERIFIED", ""}:
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default="control/gpt_supergreen_inbox.json")
    ap.add_argument("--out", default="queues/ireland_auth_retry_latest.jsonl")
    ap.add_argument("--summary", default="control/ireland_auth_retry_summary.json")
    ap.add_argument("--limit", type=int, default=24)
    args = ap.parse_args()

    payload = _load(Path(args.inbox), {})
    selected = []
    seen = set()
    scanned = 0
    ireland = 0
    for row in _iter_rows(payload):
        scanned += 1
        portal = str(row.get("portal") or row.get("source") or "").upper()
        cid = str(row.get("candidate_id") or "").strip()
        if portal != "IRELAND_ETENDERS" and not cid.upper().startswith("IE:"):
            continue
        ireland += 1
        if not cid or cid in seen or not _is_authenticity_pending(row):
            continue
        seen.add(cid)
        selected.append({
            "candidate_id": cid,
            "selection_lane": "IRELAND_AUTHENTICITY_EXACT_ID_RETRY",
            "selection_reason": "replay_exact_live_candidate_through_current_DCE_resolver_for_authoritative_evidence_only",
        })
        if len(selected) >= max(1, min(64, args.limit)):
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in selected), encoding="utf-8")
    summary = {
        "schema": "IRELAND_AUTHENTICITY_RETRY_V1",
        "scanned_rows": scanned,
        "ireland_rows_seen": ireland,
        "selected": len(selected),
        "selected_ids": [x["candidate_id"] for x in selected],
        "safety": {
            "exact_candidate_ids_only": True,
            "creates_green": False,
            "bypasses_evidence_quality": False,
            "bypasses_mandatory_gates": False,
            "bypasses_final_verdict_guard": False,
            "unknown_never_pass": True,
        },
    }
    sp = Path(args.summary)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
