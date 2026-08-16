#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from pipeline import historical_market_priors as h
except ModuleNotFoundError:
    import historical_market_priors as h


def open_text(path: Path):
    return gzip.open(path, 'rt', encoding='utf-8') if path.suffix == '.gz' else path.open('r', encoding='utf-8')


def rows(path: Path):
    with open_text(path) as fh:
        for raw in fh:
            raw=raw.strip()
            if not raw: continue
            try: r=json.loads(raw)
            except json.JSONDecodeError: continue
            if isinstance(r,dict):
                n=r.get('notice')
                yield (n if isinstance(n,dict) else r), r


def rx_any(patterns, text):
    for p in patterns or []:
        try:
            if re.search(str(p), text, re.I): return True
        except re.error:
            continue
    return False


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--priors',default='control/historical_market_priors.json')
    ap.add_argument('--out',required=True)
    ap.add_argument('--examples-per-rule',type=int,default=3)
    a=ap.parse_args()
    priors=h.load(a.priors)
    if not priors: raise SystemExit('priors not READY')

    recs=list(rows(Path(a.input)))
    country_counts=Counter(h._country(n) or 'UNKNOWN' for n,_ in recs)
    source_counts=Counter(str(n.get('source') or 'UNKNOWN') for n,_ in recs)
    rules=[]
    for idx,rule in enumerate(priors.get('lane_rules') or []):
        if not isinstance(rule,dict): continue
        pats=rule.get('patterns') or []
        negs=rule.get('negative_patterns') or []
        mode=str(rule.get('match_field') or 'search_text').casefold()
        rcountry=str(rule.get('country') or '').strip().upper()
        title_hits=0; country_hits=0; negative_blocked=0; unknown_country_hits=0
        examples=[]; mismatch_examples=[]
        for n,env in recs:
            text=h._title_text(n) if mode=='title' else h._search_text(n)
            if not text or not rx_any(pats,text): continue
            title_hits += 1
            c=h._country(n)
            if rx_any(negs,text):
                negative_blocked += 1
                continue
            if rcountry and not c:
                unknown_country_hits += 1
            if h._country_matches(rcountry,c):
                country_hits += 1
                if len(examples)<a.examples_per_rule:
                    examples.append({'candidate_id':str(env.get('canonical_notice_id') or n.get('candidate_id') or ''),'country':c,'source':n.get('source'),'title':n.get('title')})
            elif len(mismatch_examples)<a.examples_per_rule:
                mismatch_examples.append({'candidate_id':str(env.get('canonical_notice_id') or n.get('candidate_id') or ''),'country':c or 'UNKNOWN','source':n.get('source'),'title':n.get('title')})
        rules.append({
            'index':idx,'lane':rule.get('lane'),'rule_country':rcountry or 'ANY','decision':rule.get('decision'),
            'priority_bonus':rule.get('priority_bonus'),'historical_sample_size':rule.get('sample_size'),
            'pattern_hits_before_negative':title_hits,'negative_blocked':negative_blocked,
            'eligible_country_pattern_hits':country_hits,'unknown_country_pattern_hits':unknown_country_hits,
            'examples':examples,'country_mismatch_examples':mismatch_examples,
        })

    out={
        'schema':'LIVE_HISTORICAL_PRIOR_COVERAGE_AUDIT_V1',
        'input_rows':len(recs),
        'country_counts':dict(country_counts.most_common()),
        'source_counts':dict(source_counts.most_common()),
        'rules':rules,
        'totals':{
            'pattern_hits_before_negative':sum(x['pattern_hits_before_negative'] for x in rules),
            'negative_blocked':sum(x['negative_blocked'] for x in rules),
            'eligible_country_pattern_hits':sum(x['eligible_country_pattern_hits'] for x in rules),
            'rules_with_eligible_hits':sum(1 for x in rules if x['eligible_country_pattern_hits']>0),
        },
        'interpretation':'Diagnostic only. Counts never reject, delete, or establish eligibility. Overlapping rule hits may count the same notice more than once.'
    }
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out['totals'],indent=2))
    print('COUNTRIES',json.dumps(dict(country_counts.most_common(20)),ensure_ascii=False))
    for x in rules:
        if x['pattern_hits_before_negative'] or x['eligible_country_pattern_hits']:
            print(json.dumps({k:x[k] for k in ('index','lane','rule_country','priority_bonus','pattern_hits_before_negative','negative_blocked','eligible_country_pattern_hits','unknown_country_pattern_hits')},ensure_ascii=False))

if __name__=='__main__': main()
