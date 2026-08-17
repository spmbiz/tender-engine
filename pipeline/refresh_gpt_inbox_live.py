from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


# The inbox is now a work queue for GPT Web, not a verdict store.
# Final/decided opportunities live in control/final_supergreen_bank.json.
VISIBLE_REVIEW_SIGNALS = {'FINAL_SUPER_GREEN', 'GREEN', 'GREEN_PARTNERABLE'}
HARD_GPT_INBOX_BLOCKERS = {
    'rfi-no-award',
    'not-a-solicitation',
    'market-research-only',
    'us-small-business-set-aside',
    'us-citizens-only',
    'top-secret-clearance',
    'sci-eligibility',
    'security-clearance',
}


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        raw = path.read_text(encoding='utf-8', errors='replace').strip()
        obj = json.loads(raw) if raw else {}
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def load_live_review_ledger(path: Path) -> dict[str, Any]:
    """Prefer the current main-branch ledger when running inside Actions.

    DCE shards may have checked out before GPT Web added a tick. Reading the live
    Contents API prevents a late shard from resurrecting already-reviewed rows.
    Local/scheduled runs safely fall back to the checked-out file.
    """
    repo = str(os.getenv('GITHUB_REPOSITORY') or '').strip()
    token = str(os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN') or '').strip()
    if repo and token:
        url = f'https://api.github.com/repos/{repo}/contents/control/gpt_web_review_ledger.json?ref=main'
        req = urllib.request.Request(
            url,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/vnd.github.raw+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'tender-gpt-inbox/1.0',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode('utf-8', errors='replace').strip()
            obj = json.loads(raw) if raw else {}
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return load_json(path)


def key(row: dict[str, Any]) -> str:
    return str(row.get('candidate_id') or '').strip().casefold()


def open_deadline(row: dict[str, Any]) -> bool:
    raw = str(row.get('deadline') or '').strip()
    if not raw:
        return True
    try:
        return date.fromisoformat(raw[:10]) >= datetime.now(timezone.utc).date()
    except Exception:
        return True


def run_id(value: Any) -> int | None:
    s = str(value or '').strip()
    return int(s) if s.isdigit() else None


def source_run(row: dict[str, Any]) -> int | None:
    for name in ('source_dce_run_id', 'latest_dce_run_id', 'source_run', 'dce_run_id'):
        out = run_id(row.get(name))
        if out is not None:
            return out
    return None


def review_key(row: dict[str, Any]) -> str:
    stable = {
        'candidate_id': str(row.get('candidate_id') or ''),
        'source_dce_run_id': source_run(row),
        'title': str(row.get('title') or ''),
        'deadline': str(row.get('deadline') or ''),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def ledger_ticks(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = ledger.get('ticks')
    if isinstance(raw, dict):
        return {str(k).casefold(): v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        out: dict[str, dict[str, Any]] = {}
        for row in raw:
            if isinstance(row, dict) and key(row):
                out[key(row)] = row
        return out
    return {}


def is_reviewed(row: dict[str, Any], ticks: dict[str, dict[str, Any]]) -> bool:
    tick = ticks.get(key(row))
    if not tick or not bool(tick.get('reviewed', True)):
        return False
    exact = str(tick.get('review_key') or '').strip()
    if exact and exact == review_key(row):
        return True
    current_run = source_run(row)
    reviewed_run = run_id(tick.get('source_dce_run_id'))
    # A later DCE generation is allowed to re-enter GPT Web review.
    if current_run is not None and reviewed_run is not None:
        return current_run <= reviewed_run
    return True


def pending_rank(row: dict[str, Any]):
    signal = str(row.get('upstream_signal') or row.get('classification') or '').upper()
    signal_rank = 2 if signal in VISIBLE_REVIEW_SIGNALS else 1
    return (
        signal_rank,
        int(row.get('gpt_priority_score') or row.get('spm_post_dce_score') or row.get('priority_score') or 0),
        int(bool(row.get('deadline_resolved'))),
        int(row.get('evidence_gate_coverage') or 0),
        source_run(row) or 0,
    )


def normalize_hot_review(row: dict[str, Any], source_name: str = 'control/gpt_review_hot.json') -> dict[str, Any] | None:
    if not isinstance(row, dict) or not key(row) or not open_deadline(row):
        return None
    if not bool(row.get('gate_readiness')):
        return None
    coverage = int(row.get('evidence_gate_coverage') or 0)
    if coverage <= 0:
        return None

    score = int(row.get('spm_post_dce_score') or 0)
    band = str(row.get('spm_fit_band') or '').upper()
    friction = {
        str(x).strip().casefold()
        for x in (row.get('spm_friction_signals') or [])
        if str(x).strip()
    }
    if score < 40 or (band and band not in {'HOT', 'GOOD'}):
        return None
    if friction & HARD_GPT_INBOX_BLOCKERS:
        return None

    out = dict(row)
    out['review_state'] = 'PENDING_GPT_WEB'
    out['review_tick'] = False
    out['review_key'] = review_key(out)
    out['recommended_gpt_action'] = 'GPT_WEB_REVIEW_NOW'
    out['gpt_priority_score'] = max(50, min(100, score if score > 0 else int(out.get('priority_score') or 0)))
    out['upstream_signal'] = str(out.get('upstream_signal') or out.get('classification') or 'DCE_REVIEW_READY').upper()
    out['finality'] = 'NOT_A_VERDICT_GPT_WEB_MUST_REVIEW'
    out['inbox_live_source'] = source_name
    out['evidence_locator'] = {
        'dce_run_id': source_run(out),
        'shard': out.get('source_shard'),
        'candidate_id': out.get('candidate_id'),
    }
    return out


def normalize_hot_green(row: dict[str, Any]) -> dict[str, Any] | None:
    """Auto/guarded GREEN is only a high-priority GPT Web input.

    supergreen_hot is retained for compatibility, but it no longer means that the
    user-facing inbox has accepted the verdict. GPT Web still owns the final call.
    """
    if not isinstance(row, dict) or not key(row) or not open_deadline(row):
        return None
    out = dict(row)
    out['review_state'] = 'PENDING_GPT_WEB'
    out['review_tick'] = False
    out['review_key'] = review_key(out)
    out['upstream_signal'] = str(out.get('classification') or 'AUTO_GREEN').upper()
    out['recommended_gpt_action'] = 'GPT_WEB_REVIEW_NOW'
    out['gpt_priority_score'] = max(70, min(100, int(out.get('final_score') or 0)))
    out['finality'] = 'UPSTREAM_GUARDED_SIGNAL_NOT_A_GPT_WEB_VERDICT'
    out['inbox_live_source'] = 'control/supergreen_hot.json'
    out['evidence_locator'] = {
        'dce_run_id': source_run(out),
        'shard': out.get('source_shard'),
        'candidate_id': out.get('candidate_id'),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description='Build the queue of DCE-ready candidates GPT Web should review now.')
    ap.add_argument('--existing', default='control/gpt_supergreen_inbox.json')
    ap.add_argument('--final-bank', default='control/final_supergreen_bank.json')
    ap.add_argument('--hot-green', default='control/supergreen_hot.json')
    ap.add_argument('--hot-review', default='control/gpt_review_hot.json')
    ap.add_argument('--review-ledger', default='control/gpt_web_review_ledger.json')
    ap.add_argument('--out', default='control/gpt_supergreen_inbox.json')
    ap.add_argument('--max-items', type=int, default=60)
    args = ap.parse_args()

    existing = load_json(Path(args.existing))
    final_bank = load_json(Path(args.final_bank))
    hot_green = load_json(Path(args.hot_green))
    hot_review = load_json(Path(args.hot_review))
    ledger = load_live_review_ledger(Path(args.review_ledger))
    ticks = ledger_ticks(ledger)

    # Anything already in the final bank is decided and never belongs in the work inbox.
    final_items = [x for x in final_bank.get('items', []) if isinstance(x, dict) and key(x)]
    resolved = {key(x) for x in final_items}

    pending: dict[str, dict[str, Any]] = {}
    filtered_reviewed = 0
    filtered_resolved = 0

    def consider(row: dict[str, Any] | None) -> None:
        nonlocal filtered_reviewed, filtered_resolved
        if row is None:
            return
        k = key(row)
        if k in resolved:
            filtered_resolved += 1
            return
        if is_reviewed(row, ticks):
            filtered_reviewed += 1
            return
        cur = pending.get(k)
        if cur is None or pending_rank(row) >= pending_rank(cur):
            pending[k] = row

    # Carry forward still-unreviewed items from the prior inbox.
    existing_rows = existing.get('review_queue')
    if not isinstance(existing_rows, list):
        existing_rows = existing.get('pending_final_review') or []
    for raw in existing_rows:
        if isinstance(raw, dict):
            consider(normalize_hot_review(raw, 'existing_inbox'))

    # Precision-filtered DCE rows.
    for raw in hot_review.get('items', []) or []:
        if isinstance(raw, dict):
            consider(normalize_hot_review(raw))

    # Guarded/automatic GREEN is a priority signal only; GPT Web still reviews it.
    for bucket in ('final_supergreens', 'greens'):
        for raw in hot_green.get(bucket, []) or []:
            if isinstance(raw, dict):
                consider(normalize_hot_green(raw))

    rows = sorted(pending.values(), key=pending_rank, reverse=True)[:max(0, args.max_items)]

    runs: list[int] = []
    for value in (hot_review.get('latest_dce_run_id'), hot_green.get('latest_dce_run_id')):
        n = run_id(value)
        if n is not None:
            runs.append(n)
    for row in rows:
        n = source_run(row)
        if n is not None:
            runs.append(n)

    payload = {
        'schema': 'GPT_WEB_REVIEW_INBOX_V1',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'latest_source_dce_run_id': max(runs) if runs else existing.get('latest_source_dce_run_id'),
        'review_queue': rows,
        # Transitional alias so old readers do not break while the repo rolls forward.
        'pending_final_review': rows,
        'counts': {
            'pending_gpt_web_review': len(rows),
            'reviewed_ticks_total': len(ticks),
            'excluded_already_reviewed': filtered_reviewed,
            'excluded_already_in_final_bank': filtered_resolved,
        },
        'review_contract': 'This file is only GPT Web work. Every row is DCE-ready or an upstream guarded GREEN signal that still requires GPT Web review. Nothing in this inbox is a final verdict.',
        'tick_contract': 'After GPT Web reviews a pass, add one durable reviewed tick per candidate to control/gpt_web_review_ledger.json. The next rebuild removes ticked rows automatically. A later DCE run may re-enter review.',
        'final_bank_contract': 'Decided GREEN/YELLOW/RED/FINAL_SUPER_GREEN results belong in control/final_supergreen_bank.json, never mixed into this inbox.',
        'pipeline_contract': 'harvest -> Qwen/local triage -> DCE/evidence -> this GPT Web review inbox -> GPT Web review + tick -> final bank.',
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload['counts'], indent=2))


if __name__ == '__main__':
    main()
