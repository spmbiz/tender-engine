from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open('r', encoding='utf-8', errors='replace') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f'{path}:{line_no}: expected JSON object')
            rows.append(obj)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', required=True)
    ap.add_argument('--selection', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    candidates = load_jsonl(Path(args.candidates))
    selection = load_jsonl(Path(args.selection))
    by_id = {str(r.get('candidate_id')): r for r in candidates if r.get('candidate_id')}

    selected = []
    missing = []
    duplicate_selection = []
    seen = set()
    for sel in selection:
        cid = str(sel.get('candidate_id') or '').strip()
        if not cid:
            continue
        if cid in seen:
            duplicate_selection.append(cid)
            continue
        seen.add(cid)
        base = by_id.get(cid)
        if not base:
            missing.append(cid)
            continue
        rec = dict(base)
        # Selection metadata is authoritative only for analysis-control fields;
        # discovery/source fields remain the canonical harvested record.
        for key in ('preliminary_score', 'wide_read_run_id', 'status', 'selection_reason'):
            if key in sel:
                rec[key] = sel[key]
        rec['selection_manifest_candidate_id'] = cid
        selected.append(rec)

    if missing:
        raise SystemExit('Selection candidates missing from canonical discovery pool: ' + ', '.join(missing))
    if duplicate_selection:
        raise SystemExit('Duplicate candidate IDs in selection manifest: ' + ', '.join(duplicate_selection))
    if len(selected) != len(selection):
        raise SystemExit(f'Coverage mismatch: selected={len(selected)} selection={len(selection)}')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n')

    summary = {
        'canonical_candidate_pool': len(candidates),
        'selection_manifest_records': len(selection),
        'materialized_queue_records': len(selected),
        'coverage_ok': True,
        'source_run_ids': sorted({str(r.get('wide_read_run_id')) for r in selected if r.get('wide_read_run_id') is not None}),
    }
    summary_path = out.with_suffix(out.suffix + '.summary.json')
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
