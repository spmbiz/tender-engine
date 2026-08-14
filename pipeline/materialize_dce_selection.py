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


def load_selection(path: Path) -> list[dict]:
    text = path.read_text(encoding='utf-8', errors='replace').strip()
    # Compact manifests are intentionally supported even with a .jsonl suffix so
    # a large live selection can stay a tiny control-plane file.
    if text.startswith('{'):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get('candidate_ids'), list):
            default_score = min(89, int(obj.get('default_preliminary_score', 84)))
            default_status = str(obj.get('status') or 'DCE_PENDING')
            default_run = obj.get('wide_read_run_id')
            default_reason = obj.get('selection_reason')
            out = []
            for cid in obj['candidate_ids']:
                rec = {'candidate_id': str(cid), 'preliminary_score': default_score, 'status': default_status}
                if default_run is not None:
                    rec['wide_read_run_id'] = default_run
                if default_reason:
                    rec['selection_reason'] = default_reason
                out.append(rec)
            return out
    if path.suffix.lower() == '.json':
        obj = json.loads(text)
        if isinstance(obj, list):
            return [x if isinstance(x, dict) else {'candidate_id': str(x)} for x in obj]
    return load_jsonl(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', required=True)
    ap.add_argument('--selection', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    candidates = load_jsonl(Path(args.candidates))
    selection = load_selection(Path(args.selection))
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
        for key in ('preliminary_score', 'wide_read_run_id', 'status', 'selection_reason'):
            if key in sel:
                rec[key] = sel[key]
        if int(rec.get('preliminary_score') or 0) > 89:
            raise SystemExit(f'Pre-DCE score exceeds 89 for {cid}')
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
        'max_preliminary_score': max((int(r.get('preliminary_score') or 0) for r in selected), default=0),
        'source_run_ids': sorted({str(r.get('wide_read_run_id')) for r in selected if r.get('wide_read_run_id') is not None}),
    }
    summary_path = out.with_suffix(out.suffix + '.summary.json')
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
