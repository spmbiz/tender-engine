from __future__ import annotations

import argparse, glob, json, re
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


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default='control/gpt_gate_stress_batches')
    ap.add_argument('--out',default='control/gpt_bulk_prefilter_preview.json')
    args=ap.parse_args()
    root=Path(args.root)
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('conservation_pass'):
        raise SystemExit('refuse bulk prefilter without stress conservation PASS')
    rows=load_deep(root)
    expected=int(manifest.get('business_gates_in_index') or 0)
    if len(rows)!=expected:
        raise SystemExit(f'row conservation mismatch rows={len(rows)} expected={expected}')

    red=[]; preserve=[]
    reasons=Counter(); bands=Counter()
    for r in rows:
        cid=str(r.get('candidate_id') or '').strip()
        if not cid: continue
        band=str(r.get('spm_fit_band') or 'UNKNOWN').upper()
        bands[band]+=1
        # Priority rows are never bulk-rejected. Every HOT/GOOD/MAYBE gets explicit deep adjudication.
        if band in {'HOT','GOOD','MAYBE'}:
            preserve.append({'candidate_id':cid,'reason':'priority-deep-review','band':band,'deep_batch_hint':r.get('_deep_batch_hint')})
            continue
        fr={str(x) for x in (r.get('spm_friction_signals') or [])}
        fatal=sorted(fr & FATAL_FRICTIONS)
        if fatal:
            reason='fatal-procurement-friction:' + ','.join(fatal)
            red.append({'candidate_id':cid,'title':r.get('title'),'buyer':r.get('buyer'),'source_dce_run_id':(r.get('artifact_locator') or {}).get('dce_run_id'),'source_shard':(r.get('artifact_locator') or {}).get('shard'),'classification':'RED','final_score':5,'why':reason,'blockers':fatal,'bulk_rule':'FATAL_FRICTION'})
            reasons['FATAL_FRICTION']+=1
            continue
        blob=text(r)
        if LEAN.search(blob):
            preserve.append({'candidate_id':cid,'reason':'lean-native-or-brokerable-signal','band':band,'deep_batch_hint':r.get('_deep_batch_hint')})
            continue
        hit=None
        for code,rx in HARD_PHYSICAL:
            m=rx.search(blob)
            if m:
                hit=(code,' '.join(m.group(0).split())[:220]); break
        if hit:
            code,match=hit
            red.append({'candidate_id':cid,'title':r.get('title'),'buyer':r.get('buyer'),'source_dce_run_id':(r.get('artifact_locator') or {}).get('dce_run_id'),'source_shard':(r.get('artifact_locator') or {}).get('shard'),'classification':'RED','final_score':5,'why':f'Proven non-lean physical prime scope: {code}.','blockers':[code],'matched_scope':match,'bulk_rule':'HARD_PHYSICAL_NON_LEAN'})
            reasons['HARD_PHYSICAL_NON_LEAN']+=1
            continue
        preserve.append({'candidate_id':cid,'reason':'ambiguous-low-needs-review','band':band,'deep_batch_hint':r.get('_deep_batch_hint')})

    payload={
        'schema':'GPT_BULK_PREFILTER_PREVIEW_V1',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'source_stress_manifest':manifest,
        'business_gate_rows':len(rows),
        'bulk_red_count':len(red),
        'preserved_for_explicit_review_count':len(preserve),
        'band_counts':dict(bands),
        'bulk_red_reason_counts':dict(reasons),
        'bulk_red':red,
        'preserved':preserve,
        'applied_to_ledger':False,
        'contract':'Conservative assistant-authored prefilter. HOT/GOOD/MAYBE and every lean-native/brokerable or ambiguous LOW are preserved. Only explicit fatal procurement frictions or proven hard physical non-lean scopes may be bulk RED. This preview does not mutate the review ledger.'
    }
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:payload[k] for k in ('business_gate_rows','bulk_red_count','preserved_for_explicit_review_count','band_counts','bulk_red_reason_counts')},indent=2))

if __name__=='__main__': main()
