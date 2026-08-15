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

GREEN_CLASSES = {"FINAL_SUPER_GREEN", "GREEN", "GREEN_PARTNERABLE"}
REVIEW_CLASSES = {"MODEL_REVIEW_REQUIRED", "YELLOW"}
CLASS_RANK = {
    "FINAL_SUPER_GREEN": 4,
    "GREEN": 3,
    "GREEN_PARTNERABLE": 2,
    "MODEL_REVIEW_REQUIRED": 1,
    "YELLOW": 0,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    obj = json.loads(text)
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        if isinstance(obj.get("items"), list):
            return [x for x in obj["items"] if isinstance(x, dict)]
        return [obj]
    return []


def compact(rec: dict, run_id: str, shard: str, published_at: str) -> dict:
    gates = rec.get("gates") or {}
    statuses: dict[str, str] = {}
    for name, item in gates.items():
        if isinstance(item, dict):
            statuses[str(name)] = str(item.get("status") or "UNKNOWN").upper()
    resolved = {"PASS", "PASS_CONDITIONAL", "NOT_APPLICABLE"}
    classification = str(rec.get("classification") or "MODEL_REVIEW_REQUIRED").upper()
    return {
        "candidate_id": rec.get("candidate_id"),
        "title": rec.get("title"),
        "buyer": rec.get("buyer"),
        "notice_url": rec.get("notice_url"),
        "deadline": rec.get("deadline"),
        "estimated_value": rec.get("estimated_value"),
        "currency": rec.get("currency"),
        "classification": classification,
        "final_score": int(rec.get("final_score") or 0),
        "summary": rec.get("summary"),
        "content_quality": rec.get("content_quality"),
        "gate_readiness": bool(rec.get("gate_readiness")),
        "gate_statuses": statuses,
        "unresolved_gates": [k for k, v in statuses.items() if v not in resolved],
        "hard_fail_gates": [k for k, v in statuses.items() if v == "FAIL_HARD"],
        "source_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "source_shard": int(shard) if str(shard).isdigit() else shard,
        "hot_published_at": published_at,
    }


def item_key(rec: dict) -> str:
    cid = str(rec.get("candidate_id") or "").strip().casefold()
    if cid:
        return cid
    return "|".join(
        str(rec.get(k) or "").strip().casefold()
        for k in ("title", "buyer", "notice_url")
    )


def sort_key(rec: dict):
    cls = str(rec.get("classification") or "").upper()
    return (
        CLASS_RANK.get(cls, -1),
        int(rec.get("final_score") or 0),
        str(rec.get("hot_published_at") or ""),
    )


def merge_pointer(existing: dict, incoming: list[dict], run_id: str, shard: str, max_green: int, max_review: int) -> dict:
    merged: dict[str, dict] = {}
    for bucket in ("final_supergreens", "greens", "review_required_top"):
        for rec in existing.get(bucket) or []:
            if isinstance(rec, dict):
                merged[item_key(rec)] = rec
    for rec in incoming:
        merged[item_key(rec)] = rec

    items = sorted(merged.values(), key=sort_key, reverse=True)
    finals = [x for x in items if x.get("classification") == "FINAL_SUPER_GREEN"][:max_green]
    greens = [x for x in items if x.get("classification") in {"GREEN", "GREEN_PARTNERABLE"}][:max_green]
    review = [x for x in items if x.get("classification") in REVIEW_CLASSES][:max_review]

    source_runs = []
    for value in [run_id] + list(existing.get("source_runs") or []):
        s = str(value).strip()
        if s and s not in source_runs:
            source_runs.append(s)
    source_runs = source_runs[:20]

    return {
        "schema": "SUPERGREEN_HOT_V1",
        "updated_at": utc_now(),
        "latest_dce_run_id": int(run_id) if str(run_id).isdigit() else run_id,
        "latest_shard": int(shard) if str(shard).isdigit() else shard,
        "source_runs": source_runs,
        "counts": {
            "final_supergreen": len(finals),
            "green_or_partnerable": len(greens),
            "review_required_top": len(review),
        },
        "final_supergreens": finals,
        "greens": greens,
        "review_required_top": review,
        "rule": "Hot cache only. FINAL_SUPER_GREEN remains valid only when produced from authoritative DCE evidence and accepted by final_verdict_guard.py. Canonical immutable evidence remains in DCE Release assets.",
    }


def github_get(repo: str, path: str, branch: str, token: str) -> tuple[dict, str | None]:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tender-supergreen-hot/1.0",
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
        "User-Agent": "tender-supergreen-hot/1.0",
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
    ap.add_argument("--review", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--shard", required=True)
    ap.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    ap.add_argument("--branch", default="main")
    ap.add_argument("--path", default="control/supergreen_hot.json")
    ap.add_argument("--max-green", type=int, default=200)
    ap.add_argument("--max-review", type=int, default=60)
    ap.add_argument("--attempts", type=int, default=12)
    ap.add_argument("--out", default="supergreen_hot_candidate.json")
    args = ap.parse_args()

    records = load_records(Path(args.review))
    published_at = utc_now()
    incoming = [
        compact(rec, args.run_id, args.shard, published_at)
        for rec in records
        if str(rec.get("classification") or "").upper() in GREEN_CLASSES | REVIEW_CLASSES
    ]

    token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not args.repo or not token:
        payload = merge_pointer({}, incoming, args.run_id, args.shard, args.max_green, args.max_review)
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"published": False, "reason": "missing repo/token", "incoming": len(incoming)}, ensure_ascii=False))
        return

    last_error = None
    for attempt in range(1, max(1, args.attempts) + 1):
        try:
            existing, sha = github_get(args.repo, args.path, args.branch, token)
            payload = merge_pointer(existing, incoming, args.run_id, args.shard, args.max_green, args.max_review)
            Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            r = github_put(
                args.repo,
                args.path,
                args.branch,
                token,
                payload,
                sha,
                f"tender: hot supergreen DCE {args.run_id} shard {args.shard}",
            )
            if r.status_code in {200, 201}:
                print(json.dumps({
                    "published": True,
                    "attempt": attempt,
                    "incoming": len(incoming),
                    "counts": payload.get("counts"),
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

    raise SystemExit(f"hot pointer publish failed after {args.attempts} attempts: {last_error}")


if __name__ == "__main__":
    main()
