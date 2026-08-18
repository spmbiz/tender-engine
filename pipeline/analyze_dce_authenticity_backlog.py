#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "DCE_AUTHENTICITY_BACKLOG_DIAGNOSTIC_V1"


def load(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise SystemExit("inbox must be a JSON object")
    return obj


def text_status(row: dict[str, Any]) -> str:
    for key in (
        "dce_status",
        "retrieval_status",
        "content_quality",
        "evidence_quality",
        "authenticity_status",
        "review_state",
    ):
        value = row.get(key)
        if value:
            return str(value)
    dce = row.get("dce")
    if isinstance(dce, dict):
        for key in ("status", "content_quality", "evidence_quality"):
            if dce.get(key):
                return str(dce[key])
    return "UNKNOWN"


def portal(row: dict[str, Any]) -> str:
    return str(
        row.get("resolved_dce_portal")
        or row.get("portal")
        or row.get("source")
        or row.get("selection_portal")
        or "UNKNOWN"
    )


def candidate_id(row: dict[str, Any]) -> str:
    return str(row.get("candidate_id") or row.get("canonical_notice_id") or row.get("notice_id") or "")


def method_tokens(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    attempts = row.get("dce_method_attempts") or row.get("method_attempts") or []
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, dict):
                method = str(attempt.get("method") or "").strip()
                outcome = str(attempt.get("outcome") or attempt.get("status") or "").strip()
                if method:
                    out.append(method)
                if outcome:
                    out.append(f"outcome:{outcome}")
    return out


def classify_reason(row: dict[str, Any]) -> str:
    blob = json.dumps(row, ensure_ascii=False).casefold()
    rules = [
        ("AUTH_REQUIRED", ("auth_required", "authentication required", "login required", "sign in")),
        ("CAPTCHA", ("captcha_required", "captcha")),
        ("ROUTE_INCOMPLETE", ("route_incomplete", "route incomplete", "missing document url", "missing route")),
        ("GENERIC_PAGE", ("generic_public_page_unresolved", "generic public page", "landing page")),
        ("NO_PUBLIC_FILE", ("no_public_file", "no public file", "no file")),
        ("ERROR_RETRYABLE", ("error_retryable", "retryable", "timeout", "connectionerror", "readtimeout")),
        ("CONTENT_TOO_THIN", ("content_too_thin", "too thin", "thin content", "insufficient corpus")),
        ("NON_AUTHORITATIVE", ("non_authoritative", "not authoritative", "authenticity")),
    ]
    for label, needles in rules:
        if any(n in blob for n in needles):
            return label
    return "OTHER_OR_UNKNOWN"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    inbox = load(Path(args.inbox))
    queue = inbox.get("review_queue") or inbox.get("items") or []
    if not isinstance(queue, list):
        raise SystemExit("review queue is not a list")

    rows = [r for r in queue if isinstance(r, dict) and str(r.get("review_stage") or r.get("stage") or "").upper() == "DCE_AUTHENTICITY"]
    # Some inbox generations encode stage only inside review_lane/state.
    if not rows:
        rows = [
            r for r in queue if isinstance(r, dict)
            and "DCE_AUTHENTICITY" in json.dumps({k: r.get(k) for k in ("review_stage", "stage", "review_lane", "review_state", "review_contract")}, ensure_ascii=False).upper()
        ]

    by_portal = Counter()
    by_status = Counter()
    by_reason = Counter()
    by_method = Counter()
    portal_reason: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        p = portal(row)
        status = text_status(row)
        reason = classify_reason(row)
        by_portal[p] += 1
        by_status[status] += 1
        by_reason[reason] += 1
        portal_reason[p][reason] += 1
        for token in method_tokens(row):
            by_method[token] += 1
        if len(samples[reason]) < 5:
            samples[reason].append({
                "candidate_id": candidate_id(row),
                "portal": p,
                "title": row.get("title"),
                "buyer": row.get("buyer"),
                "status": status,
                "notice_url": row.get("notice_url"),
            })

    opportunities = []
    for p, total in by_portal.most_common():
        reasons = portal_reason[p]
        recoverable = sum(reasons[x] for x in ("ROUTE_INCOMPLETE", "GENERIC_PAGE", "NO_PUBLIC_FILE", "ERROR_RETRYABLE", "CONTENT_TOO_THIN"))
        opportunities.append({
            "portal": p,
            "blocked": total,
            "likely_public_recovery_target": recoverable,
            "reason_counts": dict(reasons.most_common()),
        })
    opportunities.sort(key=lambda x: (-x["likely_public_recovery_target"], -x["blocked"], x["portal"]))

    payload = {
        "schema": SCHEMA,
        "latest_source_dce_run_id": inbox.get("latest_source_dce_run_id"),
        "total_inbox_rows": len(queue),
        "dce_authenticity_rows": len(rows),
        "portal_counts": dict(by_portal.most_common()),
        "status_counts": dict(by_status.most_common()),
        "reason_counts": dict(by_reason.most_common()),
        "method_counts": dict(by_method.most_common(args.top)),
        "recovery_opportunities": opportunities[: args.top],
        "samples_by_reason": dict(samples),
        "safety": {
            "diagnostic_only": True,
            "mutates_inbox": False,
            "creates_green": False,
            "unknown_never_pass": True,
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
