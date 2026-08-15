#!/usr/bin/env python3
from __future__ import annotations

"""Build human/GPT-readable bounded evidence excerpts from historical DCE gates.

Only gate-ready authoritative corpora are included. Excerpts remain retrieval
evidence, not resolved eligibility verdicts.
"""
import argparse,json,re
from collections import defaultdict
from pathlib import Path

CATS=[
 'entity_geography','turnover_financial','references_experience','certifications_partner',
 'staffing_team','insurance_bonds','subcontracting_consortium','sla_onsite',
 'ip_data_security','award_criteria','payment_tax','forms_signatures','submission',
 'deliverables_scope','term_value']

def load(p):
    try:return json.loads(Path(p).read_text(encoding='utf-8',errors='replace'))
    except:return {}

def slug(s):
    s=re.sub(r'[^A-Za-z0-9]+','-',s or 'unknown').strip('-').lower();return s[:90] or 'unknown'

def clean(s,n=850):
    s=re.sub(r'\s+',' ',str(s or '')).strip();return s[:n]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);ap.add_argument('--per-category',type=int,default=3);a=ap.parse_args()
    root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);by=defaultdict(list)
    for gp in root.rglob('gate_snippets.json'):
        d=gp.parent;g=load(gp);e=load(d/'evidence_quality.json');c=load(d/'candidate.json')
        if not e.get('gate_readiness') or not g.get('gate_readiness'):continue
        rec={'candidate_id':c.get('candidate_id'),'sub_niche':c.get('historical_sub_niche') or 'UNKNOWN','buyer':c.get('buyer'),'title':c.get('title'),'country':c.get('country'),'portal':c.get('portal'),'categories':{}}
        cats=g.get('categories') or {}
        for cat in CATS:
            vals=cats.get(cat) or [];seen=set();items=[]
            for x in vals:
                sn=clean((x or {}).get('snippet'));key=sn[:220].casefold()
                if not sn or key in seen:continue
                seen.add(key);items.append({'match':clean((x or {}).get('match'),120),'snippet':sn})
                if len(items)>=a.per_category:break
            if items:rec['categories'][cat]=items
        by[rec['sub_niche']].append(rec)
    index=[]
    for niche,recs in sorted(by.items()):
        fname='niche-'+slug(niche)+'.md';lines=[f'# {niche} — historical DCE gate evidence','',f'Gate-ready sample: **{len(recs)}**. Excerpts are evidence for review, not eligibility verdicts.','']
        for r in recs:
            lines += [f"## {r['title']}",f"Buyer: **{r['buyer'] or 'UNKNOWN'}** · portal: `{r['portal'] or 'UNKNOWN'}` · candidate: `{r['candidate_id']}`",'']
            for cat in CATS:
                items=r['categories'].get(cat) or []
                if not items:continue
                lines.append(f'### {cat}')
                for item in items:lines.append(f"- **Match:** `{item['match']}` — {item['snippet']}")
                lines.append('')
        (out/fname).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        index.append({'sub_niche':niche,'gate_ready_candidates':len(recs),'file':fname,'candidate_ids':[r['candidate_id'] for r in recs]})
    (out/'index.json').write_text(json.dumps({'contract':'HISTORICAL_GATE_EVIDENCE_PACK_V1','subniches':index,'gate_ready_candidates':sum(x['gate_ready_candidates'] for x in index),'final_verdict_allowed':False},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'subniches':len(index),'gate_ready_candidates':sum(x['gate_ready_candidates'] for x in index)},indent=2))
if __name__=='__main__':main()
