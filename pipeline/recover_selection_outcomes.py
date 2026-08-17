#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


def git_text(ref: str, path: str) -> str:
    p = subprocess.run(['git', 'show', f'{ref}:{path}'], text=True, capture_output=True)
    return p.stdout if p.returncode == 0 else ''


def git_commits(path: str, limit: int = 160) -> list[str]:
    p = subprocess.run(['git', 'log', '--all', f'--max-count={limit}', '--format=%H', '--', path], text=True, capture_output=True)
    return [x.strip() for x in p.stdout.splitlines() if x.strip()]


def jsonl_text(text: str) -> list[dict[str, Any]]:
    out = []
    for raw in text.splitlines():
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


def json_file(path: Path) -> dict[str, Any]:
    try:
        x = json.loads(path.read_text(encoding='utf-8'))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def cid(row: dict[str, Any]) -> str:
    return str(row.get('candidate_id') or row.get('canonical_notice_id') or '').strip()


def mh(row: dict[str, Any]) -> str:
    q = row.get('qwen') if isinstance(row.get('qwen'), dict) else {}
    return str(row.get('material_fields_hash') or row.get('input_material_fields_hash') or q.get('material_fields_hash') or '').strip()


def verdict_rank(row: dict[str, Any]) -> tuple[int, int]:
    c = str(row.get('classification') or '').upper()
    return ({'FINAL_SUPER_GREEN':5,'GREEN':4,'GREEN_PARTNERABLE':3,'YELLOW':2,'RED':1}.get(c,0), int(row.get('final_score') or 0))


def triage_rank(row: dict[str, Any]) -> tuple[int, int, int]:
    action = str(row.get('recommended_gpt_action') or '').upper()
    cls = str(row.get('qwen_dce_classification') or '').upper()
    return (
        {'FINAL_REVIEW_NOW':4,'REVIEW_IF_CAPACITY':3,'NEED_MORE_DCE':2}.get(action,1),
        int(row.get('gpt_priority_score') or 0),
        {'QWEN_DCE_STRONG_FIT':4,'QWEN_DCE_FIT':3,'QWEN_DCE_MAYBE':2,'QWEN_DCE_INSUFFICIENT':1,'QWEN_DCE_REJECT':0}.get(cls,1),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--selection-ref', required=True)
    ap.add_argument('--selection-path', default='queues/qwen_live_selection_latest.jsonl')
    ap.add_argument('--attempt-ledger', default='control/dce_attempt_ledger.jsonl')
    ap.add_argument('--final-bank', default='control/final_supergreen_bank.json')
    ap.add_argument('--inbox', default='control/gpt_supergreen_inbox.json')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    selected = jsonl_text(git_text(args.selection_ref, args.selection_path))
    sel = {cid(r): r for r in selected if cid(r)}

    attempts = jsonl_text(Path(args.attempt_ledger).read_text(encoding='utf-8', errors='replace')) if Path(args.attempt_ledger).exists() else []
    attempts_by: dict[str, list[dict[str, Any]]] = {}
    for r in attempts:
        c = cid(r)
        if c in sel:
            # If both hashes exist, require exact-version identity. Terminal source
            # skips may not carry the material hash and remain valid accounting.
            sh = mh(sel[c]); ah = mh(r)
            if sh and ah and sh != ah:
                continue
            attempts_by.setdefault(c, []).append(r)

    final_rows = [x for x in json_file(Path(args.final_bank)).get('items', []) if isinstance(x, dict)]
    inbox = json_file(Path(args.inbox))
    final_by: dict[str, dict[str, Any]] = {}
    for row in final_rows + [x for x in inbox.get('confirmed_supergreens', []) if isinstance(x, dict)]:
        c = cid(row)
        if c in sel and (c not in final_by or verdict_rank(row) > verdict_rank(final_by[c])):
            final_by[c] = row

    pending_by: dict[str, dict[str, Any]] = {}
    for row in inbox.get('pending_final_review', []) or []:
        if not isinstance(row, dict):
            continue
        c = cid(row)
        if c in sel:
            pending_by[c] = row

    # Recover Qwen DCE pre-reads from history rather than trusting only the latest
    # overwritten snapshot. This makes historical selection recovery durable.
    triage_path = 'control/qwen_dce_triage_latest.jsonl'
    triage_by: dict[str, dict[str, Any]] = {}
    for commit in git_commits(triage_path):
        for row in jsonl_text(git_text(commit, triage_path)):
            c = cid(row)
            if c not in sel:
                continue
            cur = triage_by.get(c)
            if cur is None or triage_rank(row) > triage_rank(cur):
                x = dict(row)
                x['_recovered_from_commit'] = commit
                triage_by[c] = x

    details = []
    for c, s in sel.items():
        att = attempts_by.get(c, [])
        terminal = [x for x in att if str(x.get('attempt_status') or '') == 'SOURCE_SCOPED_TERMINAL_SKIP']
        materialized = [x for x in att if str(x.get('attempt_status') or '').startswith('DCE_RUN_SUCCESS')]
        f = final_by.get(c)
        p = pending_by.get(c)
        q = triage_by.get(c)
        details.append({
            'candidate_id': c,
            'material_fields_hash': mh(s),
            'notice_qwen_classification': (s.get('qwen') or {}).get('classification') if isinstance(s.get('qwen'), dict) else None,
            'attempted_exact_version': bool(att),
            'materialized_dce': bool(materialized),
            'terminal_skip': bool(terminal),
            'dce_run_ids': sorted({str(x.get('dce_run_id') or '') for x in att if x.get('dce_run_id')}),
            'final_classification': f.get('classification') if f else None,
            'final_score': f.get('final_score') if f else None,
            'current_pending_action': p.get('recommended_gpt_action') if p else None,
            'qwen_dce_classification': q.get('qwen_dce_classification') if q else None,
            'qwen_dce_lean': q.get('qwen_dce_lean') if q else None,
            'qwen_dce_route': q.get('qwen_dce_route') if q else None,
            'qwen_dce_action': q.get('recommended_gpt_action') if q else None,
            'qwen_dce_priority': q.get('gpt_priority_score') if q else None,
            'title': (f or p or q or materialized[-1] if materialized else s).get('title') if isinstance((f or p or q or materialized[-1] if materialized else s), dict) else None,
            'notice_url': (f or p or q or {}).get('notice_url') if isinstance((f or p or q or {}), dict) else None,
        })

    interesting = [x for x in details if x['final_classification'] in {'FINAL_SUPER_GREEN','GREEN','GREEN_PARTNERABLE'}]
    pending = [x for x in details if x['current_pending_action'] in {'FINAL_REVIEW_NOW','REVIEW_IF_CAPACITY'}]
    qinteresting = [x for x in details if x['qwen_dce_action'] in {'FINAL_REVIEW_NOW','REVIEW_IF_CAPACITY'} or x['qwen_dce_classification'] in {'QWEN_DCE_STRONG_FIT','QWEN_DCE_FIT'}]
    qinteresting.sort(key=lambda x: (int(x.get('qwen_dce_priority') or 0), str(x.get('qwen_dce_classification') or '')), reverse=True)

    payload = {
        'schema': 'HISTORICAL_QWEN_SELECTION_OUTCOME_RECOVERY_V1',
        'selection_ref': args.selection_ref,
        'selection_path': args.selection_path,
        'selected_total': len(sel),
        'attempted_exact_version_total': sum(x['attempted_exact_version'] for x in details),
        'materialized_dce_total': sum(x['materialized_dce'] for x in details),
        'terminal_skip_total': sum(x['terminal_skip'] for x in details),
        'not_accounted_total': sum(not x['attempted_exact_version'] for x in details),
        'durable_final_counts': dict(Counter(str(x['final_classification'] or 'NONE') for x in details)),
        'durable_green_or_better': interesting,
        'current_pending_review': pending,
        'historical_qwen_dce_interesting': qinteresting,
        'historical_qwen_dce_counts': dict(Counter(str(x['qwen_dce_classification'] or 'NONE') for x in details)),
        'details': details,
        'contract': 'FINAL/GREEN counts come only from GPT Web durable verdicts. Historical Qwen DCE rows are recovered pre-read evidence, never promoted to final by this audit.',
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k:payload[k] for k in ('selected_total','attempted_exact_version_total','materialized_dce_total','terminal_skip_total','not_accounted_total','durable_final_counts','historical_qwen_dce_counts')}, indent=2))


if __name__ == '__main__':
    main()
