from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def review_items(obj: dict[str, Any]) -> list[dict[str, Any]]:
    # `results` is the canonical field used by persisted GPT_DCE_ADJUDICATION_V1
    # files. Supporting it here makes the final-bank writer and review ledger one
    # idempotent transaction instead of two unrelated surfaces.
    for field in ('items', 'reviews', 'reviewed_items', 'results'):
        rows = obj.get(field)
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def run_id(value: Any) -> int | None:
    s = str(value or '').strip()
    return int(s) if s.isdigit() else None


def main() -> None:
    ap = argparse.ArgumentParser(description='Apply one GPT Web review pass as durable ticks.')
    ap.add_argument('--reviews', required=True, help='JSON review pass containing items/reviews/results')
    ap.add_argument('--ledger', default='control/gpt_web_review_ledger.json')
    ap.add_argument('--pass-id', required=True)
    ap.add_argument('--reviewed-at')
    ap.add_argument('--source-dce-run')
    args = ap.parse_args()

    reviews_path = Path(args.reviews)
    ledger_path = Path(args.ledger)
    reviews = load_json(reviews_path)
    ledger = load_json(ledger_path)
    now = args.reviewed_at or reviews.get('created_at') or datetime.now(timezone.utc).isoformat()
    default_run = run_id(args.source_dce_run or reviews.get('source_dce_run') or reviews.get('source_dce_run_id'))

    ticks = ledger.get('ticks') if isinstance(ledger.get('ticks'), dict) else {}
    touched: list[str] = []
    for row in review_items(reviews):
        cid = str(row.get('candidate_id') or '').strip()
        if not cid:
            continue
        source_run = run_id(row.get('source_dce_run_id')) or default_run
        verdict = str(
            row.get('gpt_web_verdict')
            or row.get('classification')
            or row.get('verdict')
            or 'REVIEWED'
        ).strip()
        tick = {
            'candidate_id': cid,
            'reviewed': True,
            'reviewed_at': now,
            'review_pass_id': args.pass_id,
            'source_dce_run_id': source_run,
            'verdict': verdict,
        }
        if row.get('review_key'):
            tick['review_key'] = str(row.get('review_key'))
        ticks[cid.casefold()] = tick
        touched.append(cid)

    passes = ledger.get('passes') if isinstance(ledger.get('passes'), list) else []
    passes = [x for x in passes if not (isinstance(x, dict) and x.get('review_pass_id') == args.pass_id)]
    passes.append({
        'review_pass_id': args.pass_id,
        'reviewed_at': now,
        'source_dce_run_id': default_run,
        'reviewed_count': len(touched),
        'candidate_ids': touched,
    })

    payload = {
        'schema': 'GPT_WEB_REVIEW_LEDGER_V1',
        'updated_at': now,
        'ticks': ticks,
        'passes': passes[-200:],
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'review_pass_id': args.pass_id, 'ticks_applied': len(touched), 'ledger_ticks_total': len(ticks)}, indent=2))


if __name__ == '__main__':
    main()
