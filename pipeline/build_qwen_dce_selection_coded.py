#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from procurement_code_prior import code_priority

FRESH = {"material_new_or_updated": 0, "recent_unseen_carryover": 1, "historical_backfill": 2}


def load_jsonl(path: Path):
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def load_snapshot(path: Path):
    import gzip
    opener = gzip.open if path.suffix == ".gz" else open
    out = {}
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            notice = row.get("notice") if isinstance(row.get("notice"), dict) else {}
            cid = str(row.get("canonical_notice_id") or row.get("candidate_id") or notice.get("candidate_id") or "").strip()
            if cid:
                out[cid] = row
    return out


def priority_key(row):
    prior = row.get("procurement_code_prior") or {}
    fresh = FRESH.get(str(row.get("selection_freshness") or "historical_backfill"), 2)
    score = int(row.get("business_fit_score") or 0) + int(prior.get("delta") or 0)
    return (fresh, -score, str(row.get("candidate_id") or ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    for name in ("state", "ledger", "snapshot", "out", "summary", "source-run"):
        ap.add_argument("--" + name, required=True)
    ap.add_argument("--blocked-state")
    ap.add_argument("--review-backlog")
    ap.add_argument("--dispatch-state")
    ap.add_argument("--attempt-ledger", default="control/dce_attempt_ledger.jsonl")
    ap.add_argument("--limit", type=int, default=160)
    ap.add_argument("--explore-share", type=float, default=.20)
    ap.add_argument("--reject-audit-share", type=float, default=.05)
    ap.add_argument("--candidate-pool-multiplier", type=int, default=4)
    args = ap.parse_args()

    limit = max(1, int(args.limit))
    multiplier = max(1, int(args.candidate_pool_multiplier))
    pool_limit = max(limit, min(2000, limit * multiplier))

    with tempfile.TemporaryDirectory(prefix="qwen-coded-selection-") as td:
        pool = Path(td) / "pool.jsonl"
        base_summary = Path(td) / "base-summary.json"
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("build_qwen_dce_selection_base.py")),
            "--state", args.state,
            "--ledger", args.ledger,
            "--snapshot", args.snapshot,
            "--out", str(pool),
            "--summary", str(base_summary),
            "--source-run", args.source_run,
            "--attempt-ledger", args.attempt_ledger,
            "--limit", str(pool_limit),
            "--explore-share", str(args.explore_share),
            "--reject-audit-share", str(args.reject_audit_share),
        ]
        for flag, value in (
            ("--blocked-state", args.blocked_state),
            ("--review-backlog", args.review_backlog),
            ("--dispatch-state", args.dispatch_state),
        ):
            if value:
                cmd += [flag, value]
        subprocess.run(cmd, check=True)

        rows = load_jsonl(pool)
        snapshot = load_snapshot(Path(args.snapshot))
        contradictions = positives = 0
        for row in rows:
            rec = snapshot.get(str(row.get("candidate_id") or ""), {})
            prior = code_priority(rec)
            row["procurement_code_prior"] = prior
            row["coded_priority_score"] = max(0, min(118, int(row.get("business_fit_score") or 0) + int(prior["delta"])))
            if prior["contradiction"]:
                contradictions += 1
            if prior["positive"]:
                positives += 1

        primary = []
        explore = []
        reject = []
        for row in rows:
            q = row.get("qwen") if isinstance(row.get("qwen"), dict) else {}
            decision = str(q.get("classification") or "").upper()
            contradiction = bool((row.get("procurement_code_prior") or {}).get("contradiction"))
            if decision in {"STRONG_FIT", "FIT"} and not contradiction:
                primary.append(row)
            elif decision == "REJECT_OBVIOUS":
                reject.append(row)
            else:
                explore.append(row)

        for arr in (primary, explore, reject):
            arr.sort(key=priority_key)

        rn = max(0, min(limit, round(limit * max(0, min(.25, args.reject_audit_share)))))
        en = max(0, min(limit - rn, round(limit * max(0, min(.5, args.explore_share)))))
        pn = max(0, limit - rn - en)
        chosen = []
        seen = set()

        def take(arr, n, lane):
            count = 0
            for row in arr:
                if count >= n or len(chosen) >= limit:
                    break
                cid = str(row.get("candidate_id") or "")
                if not cid or cid in seen:
                    continue
                out = dict(row)
                out["selection_bucket"] = lane
                prior = out.get("procurement_code_prior") or {}
                out["selection_reason"] = str(out.get("selection_reason") or "") + (
                    f" | code-prior:{int(prior.get('delta') or 0):+d}; priority-only; never eligibility"
                )
                seen.add(cid)
                chosen.append(out)
                count += 1

        take(primary, pn, "qwen-primary-coded")
        take(explore, en, "qwen-explore-coded")
        take(reject, rn, "qwen-reject-audit-coded")
        elastic = sorted(rows, key=priority_key)
        take(elastic, limit - len(chosen), "qwen-elastic-coded")

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in chosen),
            encoding="utf-8",
        )
        base = json.loads(base_summary.read_text(encoding="utf-8"))
        summary = dict(base)
        summary["schema"] = "QWEN_LIVE_DCE_SELECTION_SUMMARY_CODED_V1"
        summary["base_candidate_pool"] = len(rows)
        summary["requested_final_limit"] = limit
        summary["selected"] = len(chosen)
        summary["coded_selection_lanes"] = dict(Counter(str(x.get("selection_bucket") or "UNKNOWN") for x in chosen))
        summary["code_prior"] = {
            "positive_code_rows_in_pool": positives,
            "noncore_code_contradictions_in_pool": contradictions,
            "policy": "priority_only_never_drop_never_eligibility",
            "candidate_pool_multiplier": multiplier,
        }
        summary.setdefault("policy", {})["procurement_code_prior_never_changes_keep_or_dce_eligible"] = True
        Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
