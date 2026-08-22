from __future__ import annotations

import argparse, json, re, shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEAN = re.compile(r"\b(?:web(?:site|sites| application| applications| app| apps| development| redesign)?|cms|software|saas|cloud|mobile app|application development|digital|digitisation|digitization|graphic design|branding|brand identity|animation|audiovisual|video|podcast|social media|digital marketing|translation|transcription|copywriting|proofreading|e[- ]learning|data processing|data entry|document scanning|numerisation|numérisation|cybersecurity|artificial intelligence|machine learning|augmented reality|virtual reality|printing|impression|print|routage|mailing|reprograph|editorial|éditorial|communication|seo|search engine optimisation|generative engine optimisation)\b", re.I)

HARD_PHYSICAL: tuple[tuple[str,re.Pattern[str]], ...] = (
    ("physical-construction", re.compile(r"\b(?:construction works?|civil works?|building construction|renovation works?|roof(?:ing| replacement| repair)|road works?|bridge (?:repair|replacement|works?)|dredging|asphalt paving)\b", re.I)),
    ("physical-mep", re.compile(r"\b(?:hvac|heating|ventilation|air conditioning|chiller|plumbing|electrical works?|steam|condensate)\b.{0,90}\b(?:install|installation|replace|replacement|repair|maintenance|works?)\b|\b(?:install|installation|replace|replacement|repair|maintenance)\b.{0,90}\b(?:hvac|heating|ventilation|air conditioning|chiller|plumbing|steam|condensate)\b", re.I)),
    ("physical-waste", re.compile(r"\b(?:waste removal|solid waste collection|refuse collection|garbage collection)\b", re.I)),
    ("physical-grounds-cleaning", re.compile(r"\b(?:grounds maintenance|landscaping services?|janitorial services?|building cleaning|cleaning services?)\b", re.I)),
    ("physical-food-catering", re.compile(r"\b(?:catering services?|food supply|meal delivery|school meals)\b", re.I)),
    ("physical-transport", re.compile(r"\b(?:bus transport|passenger transport|haulage|vehicle maintenance|fleet maintenance|rail gear|fuel supply)\b", re.I)),
)

FATAL_FRICTIONS = {
    "us-sdvosb-set-aside","us-vosb-set-aside","us-wosb-set-aside","us-edwosb-set-aside",
    "us-hubzone-set-aside","us-8a-set-aside","us-direct-8a-award","us-citizens-only",
    "top-secret-clearance","sci-eligibility","rfi-no-award","not-an-award-solicitation",
    "market-research-not-solicitation","market-research-only","sources-sought",
    "SOLE_SOURCE_OR_OEM","SOURCES_SOUGHT_OR_RFI",
}


def load_deep(root: Path) -> list[dict[str,Any]]:
    rows=[]
    for p in sorted(root.glob('batch-*.json')):
        try: obj=json.loads(p.read_text(encoding='utf-8'))
        except Exception: continue
        rows.extend(x for x in (obj.get('items') or []) if isinstance(x,dict))
    return rows


def text(row: dict[str,Any]) -> str:
    parts=[str(row.get('title') or '')]
    gates=row.get('gate_evidence') if isinstance(row.get('gate_evidence'),dict) else {}
    for gate in ('deliverables_scope','term_value','staffing_team','certifications_partner','references_experience','turnover_financial','sla_onsite'):
        item=gates.get(gate)
        if isinstance(item,dict): parts.append(str(item.get('text') or ''))
    return ' '.join(parts)


def write_batches(rows:list[dict[str,Any]], out_dir:Path, schema:str, batch_size:int=10) -> None:
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True,exist_ok=True)
    files=[]
    for start in range(0,len(rows),batch_size):
        chunk=rows[start:start+batch_size]
        idx=start//batch_size
        name=f'batch-{idx:03d}.json'
        body={'schema':schema,'batch_index':idx,'start_rank':start+1,'end_rank':start+len(chunk),'count':len(chunk),'items':chunk,'instruction':'Assistant must explicitly adjudicate every row from authoritative DCE evidence. Unknown never PASS.'}
        (out_dir/name).write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        files.append({'file':name,'start_rank':start+1,'end_rank':start+len(chunk),'count':len(chunk)})
    (out_dir/'manifest.json').write_text(json.dumps({'schema':schema+'_MANIFEST','count':len(rows),'batch_size':batch_size,'batch_count':len(files),'files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default='control/gpt_gate_stress_batches')
    ap.add_argument('--out',default='control/gpt_bulk_prefilter_preview.json')
    ap.add_argument('--priority-out-dir',default='control/gpt_priority_deep_batches')
    ap.add_argument('--preserved-out-dir',default='control/gpt_preserved_low_deep_batches')
    args=ap.parse_args()
    root=Path(args.root)
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('conservation_pass'):
        raise SystemExit('refuse bulk prefilter without stress conservation PASS')
    rows=load_deep(root)
    expected=int(manifest.get('business_gates_in_index') or 0)
    if len(rows)!=expected:
        raise SystemExit(f'row conservation mismatch rows={len(rows)} expected={expected}')

    red=[]; preserve=[]; priority_rows=[]; preserved_low_rows=[]
    reasons=Counter(); bands=Counter()
    for r in rows:
        cid=str(r.get('candidate_id') or '').strip()
        if not cid: continue
        band=str(r.get('spm_fit_band') or 'UNKNOWN').upper()
        bands[band]+=1
        if band in {'HOT','GOOD','MAYBE'}:
            priority_rows.append(r)
            preserve.append({'candidate_id':cid,'reason':'priority-deep-review','band':band,'deep_batch_hint':r.get('_deep_batch_hint')})
            continue
        fr={str(x) for x in (r.get('spm_friction_signals') or [])}
        fatal=sorted(fr & FATAL_FRICTIONS)
        if fatal:
            red.append({'candidate_id':cid,'title':r.get('title'),'buyer':r.get('buyer'),'source_dce_run_id':(r.get('artifact_locator') or {}).get('dce_run_id'),'source_shard':(r.get('artifact_locator') or {}).get('shard'),'classification':'RED','final_score':5,'why':'fatal-procurement-friction:' + ','.join(fatal),'blockers':fatal,'bulk_rule':'FATAL_FRICTION'})
            reasons['FATAL_FRICTION']+=1
            continue
        blob=text(r)
        if LEAN.search(blob):
            preserved_low_rows.append(r)
            preserve.append({'candidate_id':cid,'reason':'lean-native-or-brokerable-signal','band':band,'deep_batch_hint':r.get('_deep_batch_hint')})
            continue
        hit=None
        for code,rx in HARD_PHYSICAL:
            m=rx.search(blob)
            if m: hit=(code,' '.join(m.group(0).split())[:220]); break
        if hit:
            code,match=hit
            red.append({'candidate_id':cid,'title':r.get('title'),'buyer':r.get('buyer'),'source_dce_run_id':(r.get('artifact_locator') or {}).get('dce_run_id'),'source_shard':(r.get('artifact_locator') or {}).get('shard'),'classification':'RED','final_score':5,'why':f'Proven non-lean physical prime scope: {code}.','blockers':[code],'matched_scope':match,'bulk_rule':'HARD_PHYSICAL_NON_LEAN'})
            reasons['HARD_PHYSICAL_NON_LEAN']+=1
            continue
        preserved_low_rows.append(r)
        preserve.append({'candidate_id':cid,'reason':'ambiguous-low-needs-review','band':band,'deep_batch_hint':r.get('_deep_batch_hint')})

    write_batches(priority_rows,Path(args.priority_out_dir),'GPT_PRIORITY_DEEP_REVIEW_V1',10)
    write_batches(preserved_low_rows,Path(args.preserved_out_dir),'GPT_PRESERVED_LOW_DEEP_REVIEW_V1',10)

    payload={
        'schema':'GPT_BULK_PREFILTER_PREVIEW_V2',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'source_stress_manifest':manifest,
        'business_gate_rows':len(rows),
        'bulk_red_count':len(red),
        'priority_deep_review_count':len(priority_rows),
        'preserved_low_deep_review_count':len(preserved_low_rows),
        'preserved_for_explicit_review_count':len(preserve),
        'band_counts':dict(bands),
        'bulk_red_reason_counts':dict(reasons),
        'bulk_red':red,
        'preserved':preserve,
        'applied_to_ledger':False,
        'contract':'Conservative assistant-authored prefilter. HOT/GOOD/MAYBE and every lean-native/brokerable or ambiguous LOW are emitted into explicit full-evidence deep batches. Only explicit fatal procurement frictions or proven hard physical non-lean scopes may be bulk RED. Preview does not mutate ledger.'
    }
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:payload[k] for k in ('business_gate_rows','bulk_red_count','priority_deep_review_count','preserved_low_deep_review_count','band_counts','bulk_red_reason_counts')},indent=2))

if __name__=='__main__': main()
