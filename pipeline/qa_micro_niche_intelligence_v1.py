#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, math
from collections import defaultdict
from pathlib import Path


def rows(path: Path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def fnum(v):
    try: return float(v)
    except Exception: return None


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dir',required=True); ap.add_argument('--out',required=True)
    a=ap.parse_args(); src=Path(a.dir); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    rank=rows(src/'micro_niche_rank.csv')
    examples=rows(src/'representative_examples.csv')
    winners=rows(src/'top_winners_micro_niche.csv')
    repeats=rows(src/'repeat_buyers_micro_niche.csv')

    ex=defaultdict(list)
    for r in examples:
        k=(r.get('micro_niche',''),r.get('warehouse_source') or r.get('source',''),r.get('country',''),r.get('route',''))
        ex[k].append(r)
    win=defaultdict(list)
    for r in winners:
        k=(r.get('micro_niche',''),r.get('warehouse_source') or r.get('source',''),r.get('country',''),r.get('route',''),r.get('currency',''))
        win[k].append(r)
    rep=defaultdict(list)
    for r in repeats:
        k=(r.get('micro_niche',''),r.get('warehouse_source') or r.get('source',''),r.get('country',''),r.get('route',''),r.get('currency',''))
        rep[k].append(r)

    reviewed=[]
    for r in rank:
        score=fnum(r.get('historical_spm_score')) or 0
        records=int(float(r.get('records') or 0)); buyers=int(float(r.get('buyers') or 0))
        if score < 65 or records < 3: continue
        flags=[]
        ratio=(records/buyers) if buyers else math.inf
        med=fnum(r.get('median_award_value'))
        bidder_rows=int(float(r.get('bidder_rows') or 0))
        if buyers == 0: flags.append('NO_BUYER_IDENTITY')
        if records>=100 and buyers and ratio>=10: flags.append('EXTREME_RECORDS_PER_BUYER_REVIEW')
        if records>=500 and buyers<100: flags.append('HIGH_VOLUME_LOW_BUYER_BREADTH_REVIEW')
        if med is not None and med<=1 and records>=5: flags.append('VALUE_SCHEMA_SUSPECT')
        if bidder_rows==0: flags.append('NO_BIDDER_EVIDENCE')
        if r.get('route')=='UNKNOWN': flags.append('UNKNOWN_ROUTE')
        k4=(r.get('micro_niche',''),r.get('warehouse_source') or r.get('source',''),r.get('country',''),r.get('route',''))
        k5=k4+(r.get('currency',''),)
        sample=ex.get(k4,[])[:6]
        title_blob=' || '.join((x.get('title') or '') for x in sample).lower()
        # Known false-positive signatures from prior open-world QA.
        bad_terms=['microscope','mass spectrometer','traffic signal','insurance','medical scanner','asbestos','vehicle recovery','laboratory']
        hit=[t for t in bad_terms if t in title_blob]
        if hit: flags.append('SEMANTIC_COLLISION_SAMPLE:'+','.join(hit))
        reviewed.append({**r,'records_per_buyer':round(ratio,2) if math.isfinite(ratio) else None,'qa_flags':flags,
                         'sample_titles':[x.get('title') for x in sample],
                         'sample_buyers':[x.get('buyer') for x in sample],
                         'top_winners':win.get(k5,[])[:5],
                         'top_repeat_buyers':sorted(rep.get(k5,[]),key=lambda x:int(float(x.get('procurements') or 0)),reverse=True)[:5]})

    reviewed.sort(key=lambda x: float(x.get('historical_spm_score') or 0), reverse=True)
    (out/'qa_review.json').write_text(json.dumps(reviewed,indent=2,ensure_ascii=False),encoding='utf-8')

    md=['# Micro-Niche Intelligence v1 — semantic/evidence QA','',
        'Automatic screening over the full derived ranking. Flags are review signals, not facts and not DCE gates.','']
    for r in reviewed[:60]:
        md += [f"## {r['micro_niche']} — {r.get('warehouse_source') or r.get('source')} / {r.get('country')} / {r.get('route')} / {r.get('currency')}",
               f"Score **{r.get('historical_spm_score')}** · records **{r.get('records')}** · buyers **{r.get('buyers')}** · repeat buyers **{r.get('repeat_buyers')}** · median award **{r.get('median_award_value') or 'UNKNOWN'}** · median bidders **{r.get('median_bidders') or 'UNKNOWN'}**",
               f"QA flags: `{', '.join(r['qa_flags']) if r['qa_flags'] else 'NONE_AUTOMATIC'}`",'']
        if r['sample_titles']:
            md.append('Representative historical titles:')
            md += [f"- {x}" for x in r['sample_titles'] if x]
            md.append('')
        if r['top_winners']:
            md.append('Top observed winners (fractional award weights):')
            for w in r['top_winners']:
                md.append(f"- {w.get('supplier')}: {w.get('fractional_awards')} ({w.get('share_pct')}%)")
            md.append('')
        if r['top_repeat_buyers']:
            md.append('Top repeat buyers:')
            for b in r['top_repeat_buyers']:
                md.append(f"- {b.get('buyer')}: {b.get('procurements')} procurements")
            md.append('')
    (out/'QA_REVIEW.md').write_text('\n'.join(md)+'\n',encoding='utf-8')

    summary={
      'reviewed_cohorts':len(reviewed),
      'flagged_cohorts':sum(bool(r['qa_flags']) for r in reviewed),
      'unflagged_cohorts':sum(not r['qa_flags'] for r in reviewed),
      'high_score_80_plus':sum(float(r.get('historical_spm_score') or 0)>=80 for r in reviewed),
      'high_score_flagged':sum(float(r.get('historical_spm_score') or 0)>=80 and bool(r['qa_flags']) for r in reviewed),
    }
    (out/'qa_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
