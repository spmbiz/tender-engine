from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
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


def norm(value: object) -> str:
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def identity(rec: dict) -> tuple[str, tuple[str, str] | None]:
    cid = str(rec.get('candidate_id') or '').strip().casefold()
    title = norm(rec.get('title'))
    buyer = norm(rec.get('buyer'))
    return cid, ((title, buyer) if title and buyer else None)


def load_selection(path: Path) -> list[dict]:
    text = path.read_text(encoding='utf-8', errors='replace').strip()
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
    ap.add_argument('--exclude-queue', default='queues/dce_candidates.jsonl')
    args = ap.parse_args()

    candidates = load_jsonl(Path(args.candidates))
    selection = load_selection(Path(args.selection))
    by_id = {str(r.get('candidate_id')): r for r in candidates if r.get('candidate_id')}
    exclude_rows = load_jsonl(Path(args.exclude_queue)) if args.exclude_queue else []
    excluded_ids = set()
    excluded_tb = set()
    for rec in exclude_rows:
        cid, tb = identity(rec)
        if cid:
            excluded_ids.add(cid)
        if tb:
            excluded_tb.add(tb)

    selected = []
    missing = []
    duplicate_selection = []
    excluded_existing = []
    seen = set()
    seen_tb = set()
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
        cid_key, tb_key = identity(base)
        if cid_key in excluded_ids or (tb_key and tb_key in excluded_tb):
            excluded_existing.append(cid)
            continue
        if tb_key and tb_key in seen_tb:
            duplicate_selection.append(cid)
            continue
        if tb_key:
            seen_tb.add(tb_key)
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

    # Exact duplicates are expected when the same procurement appears under aliases
    # (for example TED + national portal, or duplicated canonical rows). Keep the
    # first exact title+buyer identity and record the skipped aliases as provenance;
    # they must never abort a high-volume DCE wave.
    accounted = len(selected) + len(excluded_existing) + len(duplicate_selection)
    if accounted != len(selection):
        raise SystemExit(
            f'Coverage mismatch: selected={len(selected)} existing={len(excluded_existing)} '
            f'duplicates={len(duplicate_selection)} selection={len(selection)}'
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n')

    summary = {
        'canonical_candidate_pool': len(candidates),
        'selection_manifest_records': len(selection),
        'excluded_as_existing_exact_identity': len(excluded_existing),
        'excluded_existing_candidate_ids': excluded_existing,
        'deduplicated_exact_identity_count': len(duplicate_selection),
        'deduplicated_candidate_ids': duplicate_selection,
        'materialized_queue_records': len(selected),
        'coverage_ok': accounted == len(selection),
        'max_preliminary_score': max((int(r.get('preliminary_score') or 0) for r in selected), default=0),
        'source_run_ids': sorted({str(r.get('wide_read_run_id')) for r in selected if r.get('wide_read_run_id') is not None}),
    }
    summary_path = out.with_suffix(out.suffix + '.summary.json')
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
