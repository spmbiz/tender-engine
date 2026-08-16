#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DECISION_BASE = {'STRONG_FIT': 88, 'FIT': 78, 'MAYBE': 58, 'REJECT_OBVIOUS': 18}
LEAN_DELTA = {'HIGH': 10, 'MEDIUM': 5, 'LOW': -10, 'UNKNOWN': 0}
ROUTE_DELTA = {'DIRECT_DIGITAL': 8, 'AI_ENABLED': 7, 'MIXED': 4, 'BROKER_RESELL': 2, 'SUBCONTRACTABLE': 1, 'UNCLEAR': 0}
FRICTION_DELTA = {
    'REGULATED_GOODS': -16,
    'LICENSED_PERSONNEL': -9,
    'HEAVY_EQUIPMENT': -12,
    'CAPITAL_INTENSIVE': -12,
    'ON_SITE_SPECIALIST': -5,
    'LOCAL_PRESENCE': -5,
    'MANUFACTURER_AUTHORIZATION': -8,
    'FRAMEWORK_OR_REFERENCE_BURDEN': -4,
    'SECURITY_CLEARANCE': -9,
    'OTHER': -2,
}


def open_text(path: Path, mode: str):
    return gzip.open(path, mode + 't', encoding='utf-8') if path.suffix == '.gz' else path.open(mode, encoding='utf-8')


def read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return []
    out = []
    with open_text(path, 'r') as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def cid(row: dict[str, Any]) -> str:
    n = row.get('notice') if isinstance(row.get('notice'), dict) else {}
    return str(row.get('canonical_notice_id') or row.get('candidate_id') or n.get('candidate_id') or '').strip()


def parse_deadline(v: Any):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def blocked_ids(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return set()
    out = {str(x).strip() for x in state.get('processed_candidate_ids', []) if str(x).strip()}
    pending = state.get('pending_dce_batch')
    if isinstance(pending, dict):
        out.update(str(x).strip() for x in pending.get('candidate_ids', []) if str(x).strip())
    cooldown = state.get('dce_retry_after')
    if isinstance(cooldown, dict):
        out.update(str(x).strip() for x in cooldown if str(x).strip())
    return out


def semantic_score(row: dict[str, Any]) -> tuple[int, list[str]]:
    decision = str(row.get('classification') or '').upper()
    lean = str(row.get('lean_attractiveness') or 'UNKNOWN').upper()
    route = str(row.get('delivery_mode') or row.get('possible_delivery_route') or 'UNCLEAR').upper()
    flags = [str(x).upper() for x in (row.get('friction_flags') or [])]
    score = DECISION_BASE.get(decision, 35) + LEAN_DELTA.get(lean, 0) + ROUTE_DELTA.get(route, 0)
    reasons = [f'qwen:{decision}', f'lean:{lean}', f'route:{route}']
    for flag in flags:
        delta = FRICTION_DELTA.get(flag, -2)
        score += delta
        reasons.append(f'{delta:+d}:{flag.lower()}')
    if row.get('novelty_or_unusual_flag'):
        score += 3
        reasons.append('+3:open-world-novelty')
    if row.get('needs_gpt_review'):
        score += 2
        reasons.append('+2:gpt-review-worthy')
    return max(0, min(100, score)), reasons


def deterministic_key(candidate: str) -> str:
    return hashlib.sha256(candidate.encode('utf-8')).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description='Build a Qwen-semantic, exact-hash, high-recall DCE selection lane.')
    ap.add_argument('--state', required=True)
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--blocked-state')
    ap.add_argument('--out', required=True)
    ap.add_argument('--summary', required=True)
    ap.add_argument('--source-run', required=True)
    ap.add_argument('--limit', type=int, default=160)
    ap.add_argument('--explore-share', type=float, default=0.15)
    ap.add_argument('--reject-audit-share', type=float, default=0.05)
    args = ap.parse_args()

    ledger = {cid(x): x for x in read_jsonl(Path(args.ledger)) if cid(x)}
    snapshot = {cid(x): x for x in read_jsonl(Path(args.snapshot)) if cid(x)}
    state_rows = read_jsonl(Path(args.state))
    blocked = blocked_ids(Path(args.blocked_state)) if args.blocked_state else set()
    now = datetime.now(timezone.utc)

    valid = []
    stale = 0
    missing_snapshot = 0
    expired = 0
    for s in state_rows:
        candidate = cid(s)
        if not candidate or candidate in blocked:
            continue
        led = ledger.get(candidate)
        notice = snapshot.get(candidate)
        if not led or str(led.get('material_fields_hash') or '') != str(s.get('material_fields_hash') or ''):
            stale += 1
            continue
        if not notice:
            missing_snapshot += 1
            continue
        deadline = parse_deadline(notice.get('deadline') or notice.get('deadline_utc'))
        if deadline is not None and deadline < now:
            expired += 1
            continue
        score, reasons = semantic_score(s)
        valid.append((score, candidate, s, notice, reasons))

    valid.sort(key=lambda x: (-x[0], str(x[3].get('deadline') or '9999'), x[1]))
    rejects = [x for x in valid if str(x[2].get('classification') or '').upper() == 'REJECT_OBVIOUS']
    exploratory = [x for x in valid if str(x[2].get('classification') or '').upper() == 'MAYBE' or x[2].get('novelty_or_unusual_flag')]
    primary = [x for x in valid if str(x[2].get('classification') or '').upper() in {'STRONG_FIT', 'FIT'}]

    reject_n = max(0, min(args.limit, round(args.limit * max(0.0, min(0.25, args.reject_audit_share)))))
    explore_n = max(0, min(args.limit - reject_n, round(args.limit * max(0.0, min(0.5, args.explore_share)))))
    primary_n = max(0, args.limit - reject_n - explore_n)

    chosen: list[tuple] = []
    seen: set[str] = set()

    def take_ranked(pool, n, lane):
        added = 0
        for item in pool:
            if added >= n or len(chosen) >= args.limit:
                break
            if item[1] in seen:
                continue
            seen.add(item[1])
            chosen.append((*item, lane))
            added += 1

    take_ranked(primary, primary_n, 'qwen-primary')
    take_ranked(exploratory, explore_n, 'qwen-open-world-explore')
    reject_audit = sorted(rejects, key=lambda x: (deterministic_key(x[1]), x[1]))
    take_ranked(reject_audit, reject_n, 'qwen-reject-audit')
    take_ranked(valid, args.limit - len(chosen), 'qwen-elastic')

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for score, candidate, s, notice, reasons, lane in chosen:
        rows.append({
            'candidate_id': candidate,
            'preliminary_score': min(89, int(score)),
            'business_fit_score': min(100, int(score)),
            'selection_fit_class': f"QWEN_{str(s.get('classification') or 'UNKNOWN').upper()}",
            'wide_read_run_id': notice.get('wide_read_run_id') or args.source_run,
            'status': 'AUTO_DCE_PREFETCH_QWEN',
            'selection_portal': str(notice.get('portal') or notice.get('source') or 'UNKNOWN').upper(),
            'selection_bucket': lane,
            'selection_reason': 'QWEN semantic live routing; notice-only ranking, DCE remains authoritative | ' + ', '.join(reasons[:20]),
            'qwen': {
                'classifier_version': s.get('classifier_version'),
                'material_fields_hash': s.get('material_fields_hash'),
                'classification': s.get('classification'),
                'lean_attractiveness': s.get('lean_attractiveness'),
                'delivery_mode': s.get('delivery_mode'),
                'friction_flags': s.get('friction_flags') or [],
                'needs_gpt_review': s.get('needs_gpt_review'),
            },
        })
    with out_path.open('w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')

    summary = {
        'schema': 'QWEN_LIVE_DCE_SELECTION_SUMMARY_V1',
        'source_run': str(args.source_run),
        'state_rows': len(state_rows),
        'ledger_rows': len(ledger),
        'snapshot_rows': len(snapshot),
        'blocked_ids': len(blocked),
        'valid_exact_hash_current': len(valid),
        'stale_hash_ignored': stale,
        'missing_snapshot': missing_snapshot,
        'expired_ignored': expired,
        'selected': len(rows),
        'selection_decisions': dict(Counter(str(x.get('qwen', {}).get('classification') or 'UNKNOWN') for x in rows)),
        'selection_lean': dict(Counter(str(x.get('qwen', {}).get('lean_attractiveness') or 'UNKNOWN') for x in rows)),
        'selection_lanes': dict(Counter(str(x.get('selection_bucket') or 'UNKNOWN') for x in rows)),
        'policy': {
            'qwen_is_notice_ranking_only': True,
            'dce_is_authoritative': True,
            'rejects_are_not_deleted': True,
            'deterministic_reject_audit_share': args.reject_audit_share,
            'open_world_explore_share': args.explore_share,
            'exact_material_hash_required': True,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
