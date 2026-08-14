from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path):
    rows = []
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
                rows.append(obj)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="merged/current_candidates.jsonl")
    ap.add_argument("--selections", default="gpt_selections.jsonl")
    ap.add_argument("--out", default="queues/dce_candidates.generated.jsonl")
    ap.add_argument("--max", type=int, default=80)
    args = ap.parse_args()

    candidates = load_jsonl(Path(args.candidates))
    by_id = {str(r.get("candidate_id") or r.get("canonical_key")): r for r in candidates}
    selections = load_jsonl(Path(args.selections))

    queue = []
    missing = []
    seen = set()
    for sel in selections:
        cid = str(sel.get("candidate_id") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        base = by_id.get(cid)
        if not base:
            missing.append(cid)
            continue
        decision = str(sel.get("decision") or sel.get("status") or "QUEUE_DCE").upper()
        if decision not in {"QUEUE_DCE", "DCE_PENDING", "QUEUED", "READY"}:
            continue
        rec = dict(base)
        rec["candidate_id"] = cid
        rec["portal"] = rec.get("portal") or rec.get("source")
        rec["preliminary_score"] = sel.get("preliminary_score") or sel.get("pre_score")
        rec["gpt_reason"] = sel.get("reason") or sel.get("rationale")
        rec["gpt_packet"] = sel.get("packet")
        rec["status"] = "QUEUED"
        queue.append(rec)
        if len(queue) >= args.max:
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in queue:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    report = {
        "candidate_pool": len(candidates),
        "gpt_selections": len(selections),
        "queued": len(queue),
        "missing_candidate_ids": missing,
        "out": str(out),
    }
    Path(str(out) + ".report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
