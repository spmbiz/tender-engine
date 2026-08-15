from __future__ import annotations

import argparse
import base64
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REQUIRED_GATES = [
    "entity_geography",
    "turnover_financial",
    "references_experience",
    "certifications_partner",
    "staffing_team",
    "insurance_bonds",
    "subcontracting_consortium",
    "deliverables_scope",
    "sla_onsite",
    "term_value",
    "award_criteria",
    "forms_signatures",
    "submission",
    "ip_data_security",
]
RESOLVED_DEADLINE = {
    "CONSISTENT_NOTICE_DATE_FOUND_IN_DCE",
    "DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
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


def _snippet_text(item: object) -> tuple[str, str | None]:
    if isinstance(item, dict):
        text = str(item.get("text") or item.get("snippet") or item.get("evidence") or "")
        source = item.get("source") or item.get("file") or item.get("path")
        return text, str(source) if source else None
    return str(item or ""), None


def compact(row: dict, run_id: str, shard: str, max_snippets: int, max_chars: int) -> dict:
    snippets = row.get("gate_snippets") or {}
    evidence_by_gate: dict[str, list[dict]] = {}
    coverage = 0
    for gate in REQUIRED_GATES:
        packed: list[dict] = []
        for raw in list(snippets.get(gate) or [])[:max_snippets]:
            text, source = _snippet_text(raw)
            text = " ".join(text.split())[:max_chars]
            if not text:
                continue
            packed.append({"text": text, "source": source})
        if packed:
            coverage += 1
        evidence_by_gate[gate] = packed

    authority = row.get("authority_conflicts") or {}
    deadline = authority.get("deadline") if isinstance(authority, dict) else {}
    deadline = deadline if isinstance(deadline, dict) else {}
    deadline_status = str(deadline.get("status") or row.get("deadline_authority_status") or "MISSING")
    try:
        preliminary_score = int(float(row.get("preliminary_score") or 0))
    except Exception:
        preliminary_score = 0

    return {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title"),
        "buyer": row.get("buyer"),
        "portal": row.get("portal"),
        "notice_url": row.get("notice_url"),
        "deadline": row.get("deadline"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "preliminary_score": preliminary_score,
        "content_quality": row.get("content_quality"),
        "gate_readiness": bool(row.get("gate_readiness")),
        "deadline_authority": deadline,
        "deadline_authority_status": deadline_status,
        "deadline_resolved": deadline_status in RESOLVED_DEADLINE and not bool(deadline.get("conflict")),
        "evidence_gate_coverage": coverage,
        "evidence_by_gate": evidence_by_gate,
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "source_shard": int(shard) if str(shard).isdigit() else shard,
        "hot_ready_at": utc_now(),
        "review_contract": "Authoritative DCE evidence candidates only. ChatGPT must keep missing bidder facts/evidence UNKNOWN, must reconcile deadline authority, and must apply final_verdict_guard semantics before calling FINAL_SUPER_GREEN.",
    }


def key(rec: dict) -> str:
    cid = str(rec.get("candidate_id") or "").strip().casefold()
    if cid:
        return cid
    return "|".join(str(rec.get(k) or "").strip().casefold() for k in ("title", "buyer", "notice_url"))


def rank(rec: dict) -> tuple:
    return (
        bool(rec.get("deadline_resolved")),
        int(rec.get("preliminary_score") or 0),
        int(rec.get("evidence_gate_coverage") or 0),
        str(rec.get("hot_ready_at") or ""),
    )


def merge(existing: dict, incoming: list[dict], max_items: int, run_id: str, shard: str) -> dict:
    merged: dict[str, dict] = {}
    for rec in existing.get("items") or []:
        if isinstance(rec, dict):
            merged[key(rec)] = rec
    for rec in incoming:
        k = key(rec)
        current = merged.get(k)
        if current is None or rank(rec) >= rank(current):
            merged[k] = rec
    items = sorted(merged.values(), key=rank, reverse=True)[:max_items]
    return {
        "schema": "GPT_REVIEW_HOT_V1",
        "updated_at": utc_now(),
        "latest_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "latest_shard": int(shard) if str(shard).isdigit() else shard,
        "count": len(items),
        "items": items,
        "instruction": "Read highest-ranked items first. These are gate-ready DCE evidence packs, not final verdicts. Use only supplied authoritative evidence plus explicitly known bidder facts; unknown is never PASS. FINAL_SUPER_GREEN requires every mandatory gate resolved and authoritative deadline reconciliation.",
    }


def github_get(repo: str, path: str, branch: str, token: str) -> tuple[dict, str | None]:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tender-gpt-review-hot/1.0",
    }
    r = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    obj = r.json()
    raw = base64.b64decode(obj.get("content") or b"").decode("utf-8", errors="replace")
    try:
        current = json.loads(raw) if raw.strip() else {}
    except Exception:
        current = {}
    return current if isinstance(current, dict) else {}, obj.get("sha")


def github_put(repo: str, path: str, branch: str, token: str, payload: dict, sha: str | None, message: str) -> requests.Response:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tender-gpt-review-hot/1.0",
    }
    body = {
        "message": message,
        "content": base64.b64encode((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    return requests.put(url, headers=headers, json=body, timeout=45)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--shard", required=True)
    ap.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    ap.add_argument("--branch", default="main")
    ap.add_argument("--path", default="control/gpt_review_hot.json")
    ap.add_argument("--max-items", type=int, default=30)
    ap.add_argument("--max-snippets-per-gate", type=int, default=2)
    ap.add_argument("--max-snippet-chars", type=int, default=900)
    ap.add_argument("--attempts", type=int, default=12)
    args = ap.parse_args()

    rows = [r for r in load_jsonl(Path(args.queue)) if r.get("gate_readiness")]
    incoming = [
        compact(r, args.run_id, args.shard, max(1, args.max_snippets_per_gate), max(200, args.max_snippet_chars))
        for r in rows
    ]
    if not incoming:
        print(json.dumps({"published": False, "reason": "no_gate_ready_rows", "incoming": 0}))
        return

    token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not args.repo or not token:
        raise SystemExit("GITHUB_REPOSITORY/GH_TOKEN required for hot bank publication")

    last_error = None
    for attempt in range(1, max(1, args.attempts) + 1):
        try:
            existing, sha = github_get(args.repo, args.path, args.branch, token)
            payload = merge(existing, incoming, max(1, args.max_items), args.run_id, args.shard)
            r = github_put(
                args.repo,
                args.path,
                args.branch,
                token,
                payload,
                sha,
                f"tender: refresh GPT review bank DCE {args.run_id} shard {args.shard}",
            )
            if r.status_code in {200, 201}:
                print(json.dumps({
                    "published": True,
                    "attempt": attempt,
                    "incoming": len(incoming),
                    "bank_count": payload.get("count"),
                    "path": args.path,
                }, ensure_ascii=False))
                return
            last_error = f"GitHub PUT {r.status_code}: {r.text[:800]}"
            if r.status_code not in {409, 422}:
                raise RuntimeError(last_error)
        except Exception as exc:
            last_error = str(exc)
        if attempt < args.attempts:
            time.sleep(min(8.0, 0.35 * attempt + random.random() * 0.9))
    raise SystemExit(f"GPT review hot bank publish failed after {args.attempts} attempts: {last_error}")


if __name__ == "__main__":
    main()
