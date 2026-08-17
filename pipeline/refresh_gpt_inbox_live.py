from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


VISIBLE_FINAL_CLASSES = {'FINAL_SUPER_GREEN', 'GREEN', 'GREEN_PARTNERABLE'}

# Deterministic pre-GPT blockers. These do not require an LLM to recognize and
# should never consume scarce GPT Web final-review attention. Ambiguous business
# gates remain UNKNOWN and stay eligible for GPT only when the candidate is a
# strong SPM-fit HOT/GOOD row.
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


def confirmed_rank(row: dict[str, Any]):
    cls = str(row.get('classification') or '').upper()
    cls_rank = {'FINAL_SUPER_GREEN': 4, 'GREEN': 3, 'GREEN_PARTNERABLE': 2}.get(cls, -1)
    return (cls_rank, int(row.get('final_score') or 0), source_run(row) or 0)


def pending_rank(row: dict[str, Any]):
    action = {'FINAL_REVIEW_NOW': 4}.get(str(row.get('recommended_gpt_action') or ''), 1)
    return (
        action,
        int(row.get('gpt_priority_score') or row.get('spm_post_dce_score') or 0),
        int(bool(row.get('deadline_resolved'))),
        int(row.get('evidence_gate_coverage') or 0),
        source_run(row) or 0,
    )


def normalize_hot_review(row: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an internal recall-first DCE row into a precision-first GPT inbox row.

    GPT Web is the final adjudicator, not a discovery/filtering worker. Only
    authoritative, gate-ready, strongly SPM-relevant HOT/GOOD rows survive here.
    Obvious deterministic blockers are filtered before GPT. UNKNOWN business gates
    are never promoted to PASS by this function.
    """
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

    # Final inbox is intentionally precision-first. MAYBE/LOW/EXPLORATION stays in
    # gpt_review_hot for recall/audit, but never consumes GPT Web final review.
    if score < 40 or (band and band not in {'HOT', 'GOOD'}):
        return None
    if friction & HARD_GPT_INBOX_BLOCKERS:
        return None

    out = dict(row)
    out['native_spm_core'] = True
    out['obvious_noncore_scope'] = False
    out['qwen_dce_classification'] = out.get('qwen_dce_classification') or 'HOT_DCE_NOT_YET_QWEN_READ'
    out['qwen_dce_lean'] = out.get('qwen_dce_lean') or 'UNKNOWN'
    out['qwen_dce_route'] = out.get('qwen_dce_route') or 'UNCLEAR'
    out['recommended_gpt_action'] = 'FINAL_REVIEW_NOW'
    out['gpt_priority_score'] = max(50, min(100, score if score > 0 else int(out.get('priority_score') or 0)))
    out['finality'] = 'AUTHORITATIVE_DCE_GPT_READY_NOT_FINAL_VERDICT'
    out['inbox_live_source'] = 'control/gpt_review_hot.json'
    out['gpt_stage_contract'] = 'GPT Web is final-stage adjudication only. Discovery, DCE retrieval, deterministic rejection and SPM-fit filtering already completed upstream.'
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description='Rebuild the final-stage GPT Web inbox from durable green verdicts and precision-filtered shard-hot DCE evidence.')
    ap.add_argument('--existing', default='control/gpt_supergreen_inbox.json')
    ap.add_argument('--final-bank', default='control/final_supergreen_bank.json')
    ap.add_argument('--hot-green', default='control/supergreen_hot.json')
    ap.add_argument('--hot-review', default='control/gpt_review_hot.json')
    ap.add_argument('--out', default='control/gpt_supergreen_inbox.json')
    ap.add_argument('--max-items', type=int, default=60)
    args = ap.parse_args()

    existing = load_json(Path(args.existing))
    final_bank = load_json(Path(args.final_bank))
    hot_green = load_json(Path(args.hot_green))
    hot_review = load_json(Path(args.hot_review))

    # All durable final-bank rows are resolved and therefore suppress duplicate
    # pending review. Only actual green classes are surfaced in the GPT inbox;
    # durable RED/YELLOW remain in the final bank/audit trail, not this surface.
    final_items = [x for x in final_bank.get('items', []) if isinstance(x, dict) and key(x) and open_deadline(x)]
    resolved = {key(x) for x in final_items}
    visible_final_items = [
        x for x in final_items
        if str(x.get('classification') or '').upper() in VISIBLE_FINAL_CLASSES
    ]

    confirmed: dict[str, dict[str, Any]] = {key(x): x for x in visible_final_items}
    # A shard-hot FINAL_SUPER_GREEN is never trusted as final. Only GREEN-class
    # guarded DCE output may augment the live cache before GPT Web persistence.
    for row in (hot_green.get('greens') or []):
        if not isinstance(row, dict) or not key(row) or not open_deadline(row):
            continue
        cls = str(row.get('classification') or '').upper()
        if cls not in {'GREEN', 'GREEN_PARTNERABLE'}:
            continue
        cur = confirmed.get(key(row))
        live = dict(row)
        live['finality'] = 'GUARDED_DCE_HOT_GREEN_NOT_FINAL_SUPERGREEN'
        live['inbox_live_source'] = 'control/supergreen_hot.json'
        if cur is None or confirmed_rank(live) > confirmed_rank(cur):
            confirmed[key(row)] = live

    pending: dict[str, dict[str, Any]] = {}
    existing_pending_total = 0
    existing_pending_kept = 0
    for raw in existing.get('pending_final_review', []) or []:
        if not isinstance(raw, dict):
            continue
        existing_pending_total += 1
        row = normalize_hot_review(raw)
        if row is None or key(row) in resolved:
            continue
        pending[key(row)] = row
        existing_pending_kept += 1

    hot_review_total = 0
    hot_review_kept = 0
    for raw in hot_review.get('items', []) or []:
        if not isinstance(raw, dict):
            continue
        hot_review_total += 1
        row = normalize_hot_review(raw)
        if row is None or key(row) in resolved:
            continue
        cur = pending.get(key(row))
        if cur is None or pending_rank(row) >= pending_rank(cur):
            pending[key(row)] = row
        hot_review_kept += 1

    pending_rows = sorted(pending.values(), key=pending_rank, reverse=True)[:max(0, args.max_items)]
    confirmed_rows = sorted(confirmed.values(), key=confirmed_rank, reverse=True)

    runs: list[int] = []
    for v in (
        existing.get('latest_source_dce_run_id'),
        hot_green.get('latest_dce_run_id'),
        hot_review.get('latest_dce_run_id'),
    ):
        n = run_id(v)
        if n is not None:
            runs.append(n)
    for row in confirmed_rows + pending_rows:
        n = source_run(row)
        if n is not None:
            runs.append(n)
    latest = max(runs) if runs else existing.get('latest_source_dce_run_id')

    payload = {
        'schema': 'GPT_INSTANT_SUPERGREEN_INBOX_V5_FINAL_STAGE',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'latest_source_dce_run_id': latest,
        'confirmed_supergreens': confirmed_rows,
        'pending_final_review': pending_rows,
        'counts': {
            'confirmed_supergreens': sum(str(x.get('classification') or '').upper() == 'FINAL_SUPER_GREEN' for x in confirmed_rows),
            'confirmed_green_total': sum(str(x.get('classification') or '').upper() in {'FINAL_SUPER_GREEN', 'GREEN'} for x in confirmed_rows),
            'confirmed_or_partnerable_green_total': len(confirmed_rows),
            'resolved_total': len(final_items),
            'resolved_non_green_hidden_from_inbox': len(final_items) - len(visible_final_items),
            'pending_final_review': len(pending_rows),
            'review_now': len(pending_rows),
            'existing_pending_filtered': max(0, existing_pending_total - existing_pending_kept),
            'hot_review_filtered': max(0, hot_review_total - hot_review_kept),
            'live_hot_review_items': sum(x.get('inbox_live_source') == 'control/gpt_review_hot.json' for x in pending_rows),
            'live_hot_green_items': sum(x.get('inbox_live_source') == 'control/supergreen_hot.json' for x in confirmed_rows),
        },
        'answer_contract': 'Read this file only for end-of-pipeline opportunities. Durable RED/YELLOW and internal MAYBE/LOW/exploration rows are deliberately excluded. Pending rows are authoritative-DCE, gate-ready, HOT/GOOD SPM-fit candidates awaiting only GPT Web final adjudication. Unknown is never PASS.',
        'finality_rule': 'Only GPT Web final adjudication from authoritative DCE evidence may create or persist FINAL_SUPER_GREEN in the final bank. GitHub Actions never calls OpenAI and never waits for GPT Web.',
        'pipeline_contract': 'harvest -> Qwen/local triage -> DCE -> deterministic evidence/gates/SPM-fit rejection -> this GPT-ready inbox -> GPT Web final adjudication -> final bank. GPT Web is not a pipeline dependency and cannot block upstream processing.',
        'live_contract': 'DCE shards rebuild this file directly. The scheduled inbox refresh is only a repair/fallback path; no OpenAI API key or remote LLM call is required to reach the inbox.',
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload['counts'], indent=2))


if __name__ == '__main__':
    main()
