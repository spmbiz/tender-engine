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

from dce_attempt_ledger import load_attempt_index, was_attempted

DECISION_BASE = {'STRONG_FIT': 86, 'FIT': 68, 'MAYBE': 42, 'REJECT_OBVIOUS': 5}
LEAN_DELTA = {'HIGH': 10, 'MEDIUM': 5, 'LOW': -10, 'UNKNOWN': 0}
ROUTE_DELTA = {'DIRECT_DIGITAL': 8, 'AI_ENABLED': 7, 'MIXED': 4, 'BROKER_RESELL': 2, 'SUBCONTRACTABLE': 1, 'UNCLEAR': 0}
FRICTION_DELTA = {
    'REGULATED_GOODS': -16,
    'LICENSED_PERSONNEL': -12,
    'HEAVY_EQUIPMENT': -12,
    'CAPITAL_INTENSIVE': -12,
    'ON_SITE_SPECIALIST': -7,
    'LOCAL_PRESENCE': -6,
    'MANUFACTURER_AUTHORIZATION': -9,
    'FRAMEWORK_OR_REFERENCE_BURDEN': -5,
    'SECURITY_CLEARANCE': -12,
    'OTHER': -2,
}
DEFAULT_FRESH_HOURS = 24
FRESHNESS_LABELS = {0: 'material_new_or_updated', 1: 'recent_unseen_carryover', 2: 'historical_backfill'}


def open_text(p: Path, m: str):
    return gzip.open(p, m + 't', encoding='utf-8') if p.suffix == '.gz' else p.open(m, encoding='utf-8')


def read_jsonl(p: Path | None):
    if not p or not p.exists() or p.stat().st_size == 0:
        return []
    out = []
    with open_text(p, 'r') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                x = json.loads(raw)
            except Exception:
                continue
            if isinstance(x, dict):
                out.append(x)
    return out


def read_json(p: Path | None):
    if not p or not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        x = json.loads(p.read_text(encoding='utf-8'))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def cid(r):
    n = r.get('notice') if isinstance(r.get('notice'), dict) else {}
    return str(r.get('canonical_notice_id') or r.get('candidate_id') or n.get('candidate_id') or '').strip()


def mh(r):
    return str(r.get('material_fields_hash') or r.get('input_material_fields_hash') or '').strip()


def parse_deadline(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def freshness_rank(ledger_row, *, now=None, fresh_hours=DEFAULT_FRESH_HOURS):
    """0=current material change, 1=recently first-seen, 2=historical backlog.

    This mirrors the Qwen input priority so freshness survives the semantic stage
    instead of being lost immediately when the DCE shortlist is rebuilt from
    cumulative classification state.
    """
    event = str((ledger_row or {}).get('ledger_event') or '').upper()
    if event in {'NEW', 'UPDATED'}:
        return 0
    current = now or datetime.now(timezone.utc)
    first = parse_deadline((ledger_row or {}).get('first_seen_at'))
    if first is not None:
        age_hours = (current - first).total_seconds() / 3600
        if -1 <= age_hours <= fresh_hours:
            return 1
    return 2


def controller_blocked_ids(p):
    s = read_json(p)
    o = {str(x).strip() for x in s.get('processed_candidate_ids', []) if str(x).strip()}
    q = s.get('pending_dce_batch')
    if isinstance(q, dict):
        o.update(str(x).strip() for x in q.get('candidate_ids', []) if str(x).strip())
    c = s.get('dce_retry_after')
    if isinstance(c, dict):
        o.update(str(x).strip() for x in c if str(x).strip())
    return o


def reviewed_ids(p):
    d = read_json(p)
    items = d.get('items') if isinstance(d.get('items'), list) else []
    return {cid(x) for x in items if isinstance(x, dict) and cid(x)}


def dispatch_cooldown_ids(p, now):
    d = read_json(p)
    recs = d.get('records') if isinstance(d.get('records'), dict) else {}
    o = set()
    for c, r in recs.items():
        if isinstance(r, dict):
            x = parse_deadline(r.get('retry_after_utc'))
            if x and x > now:
                o.add(str(c).strip())
    return o


def semantic_score(r):
    d = str(r.get('classification') or '').upper()
    l = str(r.get('lean_attractiveness') or 'UNKNOWN').upper()
    route = str(r.get('delivery_mode') or 'UNCLEAR').upper()
    flags = [str(x).upper() for x in (r.get('friction_flags') or [])]
    score = DECISION_BASE.get(d, 30) + LEAN_DELTA.get(l, 0) + ROUTE_DELTA.get(route, 0)
    reasons = [
        f'qwen:{d}',
        f'lean:{l}',
        f'route:{route}',
        f"survival:{str(r.get('survival_decision') or 'KEEP').upper()}",
        f"dce_eligible:{bool(r.get('dce_eligible', True))}",
    ]
    for flag in flags:
        delta = FRICTION_DELTA.get(flag, -2)
        score += delta
        reasons.append(f'{delta:+d}:{flag.lower()}')
    if r.get('novelty_or_unusual_flag'):
        score += 3
        reasons.append('+3:open-world-novelty')
    if r.get('needs_gpt_review'):
        score += 2
        reasons.append('+2:gpt-review-worthy')
    if str(r.get('survival_decision') or 'KEEP').upper() == 'DROP':
        score -= 70
    if not bool(r.get('dce_eligible', True)):
        score -= 35
    return max(0, min(100, score)), reasons


def key(c):
    return hashlib.sha256(c.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    for a in ['state', 'ledger', 'snapshot', 'out', 'summary', 'source-run']:
        ap.add_argument('--' + a, required=True)
    ap.add_argument('--blocked-state')
    ap.add_argument('--review-backlog')
    ap.add_argument('--dispatch-state')
    ap.add_argument('--attempt-ledger', default='control/dce_attempt_ledger.jsonl')
    ap.add_argument('--limit', type=int, default=160)
    ap.add_argument('--explore-share', type=float, default=.20)
    ap.add_argument('--reject-audit-share', type=float, default=.05)
    args = ap.parse_args()

    ledger = {cid(x): x for x in read_jsonl(Path(args.ledger)) if cid(x)}
    snapshot = {cid(x): x for x in read_jsonl(Path(args.snapshot)) if cid(x)}
    state_rows = read_jsonl(Path(args.state))
    now = datetime.now(timezone.utc)

    bc = controller_blocked_ids(Path(args.blocked_state)) if args.blocked_state else set()
    rp = Path(args.review_backlog) if args.review_backlog else Path('control/gpt_review_backlog.json')
    dp = Path(args.dispatch_state) if args.dispatch_state else Path('control/qwen_live/dispatch_state.json')
    blocked = bc | reviewed_ids(rp) | dispatch_cooldown_ids(dp, now)
    attempt_index = load_attempt_index(Path(args.attempt_ledger)) if args.attempt_ledger else {}

    valid = []
    stale = missing = expired = attempted = 0
    for s in state_rows:
        c = cid(s)
        if not c or c in blocked:
            continue
        led = ledger.get(c)
        n = snapshot.get(c)
        if not led or mh(led) != mh(s):
            stale += 1
            continue
        if not n:
            missing += 1
            continue
        raw = n.get('deadline') or n.get('deadline_utc')
        dl = parse_deadline(raw)
        if dl and dl < now:
            expired += 1
            continue

        # Hard upstream anti-repeat barrier. The Qwen rolling shortlist must contain
        # only exact notice versions that DCE has never already attempted. This is
        # deliberately the same durable identity policy used by materialization, so
        # downstream never wastes cycles rediscovering already-consumed rows.
        probe = {
            'candidate_id': c,
            'material_fields_hash': mh(s),
            'wide_read_run_id': n.get('wide_read_run_id') or n.get('source_discovery_run') or args.source_run,
        }
        if was_attempted(probe, attempt_index):
            attempted += 1
            continue

        score, reasons = semantic_score(s)
        if str(s.get('classification') or '').upper() == 'STRONG_FIT' and dl is None:
            score = min(score, 79)
            reasons.append('cap:deadline-unverified')
        fresh = freshness_rank(led, now=now)
        reasons.append(f'freshness:{FRESHNESS_LABELS[fresh]}')
        valid.append((fresh, score, c, s, n, reasons))

    # Freshness is a lane-level scheduling priority, not a quality-score boost:
    # current material changes are exhausted first, then recent unseen carryover,
    # then historical backfill. Within each class, semantic quality remains king.
    valid.sort(key=lambda x: (x[0], -x[1], str(x[4].get('deadline') or '9999'), x[2]))
    eligible = [
        x for x in valid
        if str(x[3].get('survival_decision') or 'KEEP').upper() == 'KEEP'
        and bool(x[3].get('dce_eligible', True))
    ]
    primary = [x for x in eligible if str(x[3].get('classification') or '').upper() in {'STRONG_FIT', 'FIT'}]
    exploratory = [
        x for x in eligible
        if str(x[3].get('classification') or '').upper() == 'MAYBE' or x[3].get('novelty_or_unusual_flag')
    ]
    rejects = [
        x for x in valid
        if str(x[3].get('classification') or '').upper() == 'REJECT_OBVIOUS'
        or str(x[3].get('survival_decision') or '').upper() == 'DROP'
        or not bool(x[3].get('dce_eligible', True))
    ]

    rn = max(0, min(args.limit, round(args.limit * max(0, min(.25, args.reject_audit_share)))))
    en = max(0, min(args.limit - rn, round(args.limit * max(0, min(.5, args.explore_share)))))
    pn = max(0, args.limit - rn - en)
    chosen = []
    seen = set()

    def take(pool, n, lane):
        k = 0
        for item in pool:
            if k >= n or len(chosen) >= args.limit:
                break
            if item[2] in seen:
                continue
            seen.add(item[2])
            chosen.append((*item, lane))
            k += 1

    take(primary, pn, 'qwen-primary')
    take(exploratory, en, 'qwen-open-world-explore')
    take(sorted(rejects, key=lambda x: (x[0], key(x[2]), x[2])), rn, 'qwen-reject-audit')
    take(eligible, args.limit - len(chosen), 'qwen-elastic')

    rows = []
    for fresh, score, c, s, n, reasons, lane in chosen:
        rows.append({
            'candidate_id': c,
            'preliminary_score': min(89, int(score)),
            'business_fit_score': min(100, int(score)),
            'selection_fit_class': f"QWEN_{str(s.get('classification') or 'UNKNOWN').upper()}",
            'wide_read_run_id': n.get('wide_read_run_id') or args.source_run,
            'status': 'AUTO_DCE_PREFETCH_QWEN',
            'selection_portal': str(n.get('portal') or n.get('source') or 'UNKNOWN').upper(),
            'selection_bucket': lane,
            'selection_freshness': FRESHNESS_LABELS[fresh],
            'selection_reason': 'QWEN calibrated semantic routing; notice-only ranking, DCE remains authoritative | ' + ', '.join(reasons[:24]),
            'qwen': {
                'classifier_version': s.get('classifier_version'),
                'business_calibration_version': s.get('business_calibration_version'),
                'material_fields_hash': mh(s),
                'classification': s.get('classification'),
                'survival_decision': s.get('survival_decision'),
                'dce_eligible': s.get('dce_eligible'),
                'lean_attractiveness': s.get('lean_attractiveness'),
                'delivery_mode': s.get('delivery_mode'),
                'friction_flags': s.get('friction_flags') or [],
                'needs_gpt_review': s.get('needs_gpt_review'),
            },
        })

    op = Path(args.out)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(''.join(json.dumps(x, ensure_ascii=False, separators=(',', ':')) + '\n' for x in rows), encoding='utf-8')

    summary = {
        'schema': 'QWEN_LIVE_DCE_SELECTION_SUMMARY_V4',
        'generated_at_utc': now.replace(microsecond=0).isoformat(),
        'source_run': str(args.source_run),
        'state_rows': len(state_rows),
        'ledger_rows': len(ledger),
        'snapshot_rows': len(snapshot),
        'blocked_ids': len(blocked),
        'durable_attempted_exact_versions_ignored': attempted,
        'valid_exact_hash_current_unattempted': len(valid),
        'eligible_keep_for_dce': len(eligible),
        'stale_hash_ignored': stale,
        'missing_snapshot': missing,
        'expired_ignored': expired,
        'selected': len(rows),
        'selection_decisions': dict(Counter(str(x.get('qwen', {}).get('classification') or 'UNKNOWN') for x in rows)),
        'selection_survival': dict(Counter(str(x.get('qwen', {}).get('survival_decision') or 'UNKNOWN') for x in rows)),
        'selection_lanes': dict(Counter(str(x.get('selection_bucket') or 'UNKNOWN') for x in rows)),
        'selection_freshness': dict(Counter(str(x.get('selection_freshness') or 'UNKNOWN') for x in rows)),
        'policy': {
            'keep_is_not_fit': True,
            'drop_is_retained_in_state_but_not_primary_dce': True,
            'dce_eligible_required_for_primary_and_explore': True,
            'reject_audit_preserved': True,
            'exact_material_hash_required': True,
            'durable_dce_attempts_excluded_before_ranking': True,
            'deadline_unverified_caps_strong_priority': True,
            'freshness_preempts_backfill_within_dce_lanes': True,
            'freshness_is_not_eligibility_truth': True,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
