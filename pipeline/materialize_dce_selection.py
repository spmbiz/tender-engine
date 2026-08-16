from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

QWEN_STATUS = 'AUTO_DCE_PREFETCH_QWEN'
SPM_CORE = re.compile(
    r'\b(?:website|web ?app|web portal|site web|web development|web design|application development|mobile app|'
    r'cms\b|hosting|web maintenance|software development|saas\b|digital platform|workflow automation|robotic process automation|rpa\b|'
    r'animation|video production|film production|video editing|graphic design|visual identity|brand identity|content creation|copywriting|editorial|'
    r'translation|transcription|proofreading|printing services?|brochures?|leaflets?|signage|promotional goods?|digitization|digitisation|scanning|'
    r'document management|e[- ]learning|digital learning|training content|media monitoring|social listening|social media|digital marketing|'
    r'market research|survey services?|data processing|data entry|api integration|publication design|typesetting)\b', re.I
)
HARD_NONCORE = re.compile(
    r'\b(?:construction|civil works?|road works?|renovation works?|roofing|masonry|excavation|demolition|security guard|security officer|'
    r'patient transport|ambulance|medical staffing|physician services?|nursing services?|generator maintenance|chiller maintenance|vehicle maintenance|'
    r'aircraft maintenance|ship repair|firefighting vehicle|fire truck|fuel delivery|diesel delivery|ammunition|weapon|herbicide|pest control|'
    r'laundry services?|food services?|catering services?|electrical works?|plumbing works?|hvac works?|painting works?|insulation works?|snow clearing|'
    r'waste collection|janitorial|cleaning services?|laboratory equipment|scientific equipment|valves?|spare parts?|machinery|furniture)\b', re.I
)
INFO_ONLY = re.compile(r'\b(?:sources sought|industry day|request for information|\brfi\b|special notice|prior information notice|market consultation|award notice|contract award)\b', re.I)


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


def qwen_pre_admission(base: dict, sel: dict) -> tuple[bool, str]:
    if str(sel.get('status') or '').upper() != QWEN_STATUS:
        return True, 'not_qwen_lane'
    title = str(base.get('title') or '')
    desc = str(base.get('description') or base.get('summary') or '')
    category = str(base.get('cpv_or_category') or '')
    text = f'{title} {desc[:5000]} {category}'
    if INFO_ONLY.search(title):
        return False, 'qwen_information_only'
    core = bool(SPM_CORE.search(text))
    if HARD_NONCORE.search(text) and not core:
        return False, 'qwen_obvious_noncore_hard_scope'
    if core:
        return True, 'qwen_real_notice_spm_core'
    q = sel.get('qwen') if isinstance(sel.get('qwen'), dict) else {}
    route = str(q.get('delivery_mode') or '').upper()
    lean = str(q.get('lean_attractiveness') or '').upper()
    novelty = bool(q.get('novelty_or_unusual_flag') or q.get('unusual_or_novel'))
    bucket = str(sel.get('selection_bucket') or '').lower()
    # Preserve a deterministic exploration slice so high recall survives, but
    # never let a model-only FIT label flood the expensive DCE layer again.
    explore = novelty or 'explor' in bucket or (route in {'DIRECT_DIGITAL','AI_ENABLED'} and lean in {'HIGH','MEDIUM'})
    if explore:
        cid = str(base.get('candidate_id') or '')
        keep = int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16) % 5 == 0
        return keep, 'qwen_exploration_20pct' if keep else 'qwen_noncore_model_only_deferred'
    return False, 'qwen_noncore_model_only_deferred'


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
    excluded_qwen_pre_admission = []
    qwen_admission_reasons: dict[str, int] = {}
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
            # Qwen's live queue is persisted independently from any one discovery
            # snapshot. A few rows can therefore refer to a notice discovered in a
            # different/newer canonical harvest. Do not let those stale cross-snapshot
            # references abort an otherwise valid DCE batch; retain them in the
            # persisted Qwen queue and report them explicitly for a later matching run.
            missing.append(cid)
            continue
        cid_key, tb_key = identity(base)
        if cid_key in excluded_ids or (tb_key and tb_key in excluded_tb):
            excluded_existing.append(cid)
            continue
        if tb_key and tb_key in seen_tb:
            duplicate_selection.append(cid)
            continue
        allowed, admission_reason = qwen_pre_admission(base, sel)
        qwen_admission_reasons[admission_reason] = qwen_admission_reasons.get(admission_reason, 0) + 1
        if not allowed:
            excluded_qwen_pre_admission.append({'candidate_id': cid, 'reason': admission_reason})
            continue
        if tb_key:
            seen_tb.add(tb_key)
        rec = dict(base)
        for key in ('preliminary_score', 'business_fit_score', 'wide_read_run_id', 'status', 'selection_reason', 'selection_bucket', 'selection_fit_class', 'qwen'):
            if key in sel:
                rec[key] = sel[key]
        rec['qwen_pre_admission_reason'] = admission_reason
        if int(rec.get('preliminary_score') or 0) > 89:
            raise SystemExit(f'Pre-DCE score exceeds 89 for {cid}')
        rec['selection_manifest_candidate_id'] = cid
        selected.append(rec)

    accounted = len(selected) + len(missing) + len(excluded_existing) + len(duplicate_selection) + len(excluded_qwen_pre_admission)
    if accounted != len(selection):
        raise SystemExit(
            f'Coverage mismatch: selected={len(selected)} missing_snapshot={len(missing)} existing={len(excluded_existing)} '
            f'duplicates={len(duplicate_selection)} qwen_deferred={len(excluded_qwen_pre_admission)} selection={len(selection)}'
        )
    if selection and not selected:
        raise SystemExit(
            'Selection produced zero materializable DCE candidates; refusing to publish an empty batch. '
            f'missing_snapshot={len(missing)} existing={len(excluded_existing)} duplicates={len(duplicate_selection)} '
            f'qwen_deferred={len(excluded_qwen_pre_admission)}'
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n')

    summary = {
        'canonical_candidate_pool': len(candidates),
        'selection_manifest_records': len(selection),
        'missing_from_source_snapshot_count': len(missing),
        'missing_from_source_snapshot_candidate_ids': missing,
        'excluded_as_existing_exact_identity': len(excluded_existing),
        'excluded_existing_candidate_ids': excluded_existing,
        'deduplicated_exact_identity_count': len(duplicate_selection),
        'deduplicated_candidate_ids': duplicate_selection,
        'qwen_pre_admission_deferred_count': len(excluded_qwen_pre_admission),
        'qwen_pre_admission_deferred': excluded_qwen_pre_admission,
        'qwen_pre_admission_reasons': qwen_admission_reasons,
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
