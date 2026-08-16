#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any, Iterable


def open_text(path: Path, mode: str):
    return gzip.open(path, mode + 't', encoding='utf-8') if path.suffix == '.gz' else path.open(mode, encoding='utf-8')


def read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return []
    out: list[dict[str, Any]] = []
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


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_text(path, 'w') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def cid(row: dict[str, Any]) -> str:
    n = row.get('notice') if isinstance(row.get('notice'), dict) else {}
    return str(row.get('canonical_notice_id') or row.get('candidate_id') or n.get('candidate_id') or '').strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get('material_fields_hash') or row.get('input_material_fields_hash') or '').strip()


def main() -> None:
    ap = argparse.ArgumentParser(description='Overlay exact-hash Qwen state onto a freshly built notice ledger without changing notice identity.')
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--classification-queue', required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--summary', required=True)
    ap.add_argument('--classifier-version', required=True)
    args = ap.parse_args()

    ledger_path = Path(args.ledger)
    queue_path = Path(args.classification_queue)
    state_rows = read_jsonl(Path(args.state))
    ledger_rows = read_jsonl(ledger_path)
    queue_rows = read_jsonl(queue_path)

    state: dict[str, dict[str, Any]] = {}
    for row in state_rows:
        candidate = cid(row)
        if not candidate or str(row.get('classifier_version') or '') != args.classifier_version:
            continue
        if not material_hash(row):
            continue
        state[candidate] = row

    applied = 0
    stale = 0
    for row in ledger_rows:
        candidate = cid(row)
        s = state.get(candidate)
        if not s:
            continue
        if material_hash(s) != str(row.get('material_fields_hash') or ''):
            stale += 1
            continue
        row['classifier_model'] = s.get('classifier_model')
        row['classifier_quant'] = s.get('classifier_quant')
        row['classifier_prompt_version'] = s.get('classifier_prompt_version')
        row['classifier_version'] = s.get('classifier_version')
        row['classification'] = s.get('classification')
        row['confidence'] = s.get('confidence')
        row['lean_attractiveness'] = s.get('lean_attractiveness')
        row['delivery_mode'] = s.get('delivery_mode')
        row['friction_flags'] = s.get('friction_flags') if isinstance(s.get('friction_flags'), list) else []
        row['novelty_or_unusual_flag'] = s.get('novelty_or_unusual_flag')
        row['needs_gpt_review'] = s.get('needs_gpt_review')
        row['classified_at'] = s.get('classified_at_utc') or s.get('classified_at')
        row['needs_reclassification'] = False
        row['classification_stale'] = False
        applied += 1

    remaining: list[dict[str, Any]] = []
    already = 0
    for envelope in queue_rows:
        candidate = cid(envelope)
        s = state.get(candidate)
        if s and material_hash(s) == material_hash(envelope):
            already += 1
            continue
        remaining.append(envelope)

    write_jsonl(ledger_path, ledger_rows)
    write_jsonl(queue_path, remaining)

    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {}
    summary['target_classifier_version'] = args.classifier_version
    summary['classification_queue'] = len(remaining)
    summary['qwen_state_rows_seen'] = len(state_rows)
    summary['qwen_state_rows_current_version'] = len(state)
    summary['qwen_state_exact_hash_applied'] = applied
    summary['qwen_state_stale_hash_ignored'] = stale
    summary['classification_queue_satisfied_from_state'] = already
    summary.setdefault('rules', {})['classification_state'] = (
        'A notice is considered classified only when canonical_notice_id, material_fields_hash, and classifier_version all match.'
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'ledger_rows': len(ledger_rows),
        'state_rows': len(state_rows),
        'exact_hash_applied': applied,
        'stale_hash_ignored': stale,
        'queue_before': len(queue_rows),
        'queue_after': len(remaining),
    }, indent=2))


if __name__ == '__main__':
    main()
