#!/usr/bin/env python3
from __future__ import annotations

"""Aggregate historical DCE resolver/evidence/gate research by audited sub-niche.

Gate hit rates are retrieval-signal prevalence, not resolved mandatory
requirements. Only authoritative gate-ready corpora contribute to gate signals.
"""
import argparse,json
from collections import Counter,defaultdict
from pathlib import Path

CANONICAL=[
 'entity_geography','turnover_financial','references_experience','certifications_partner',
 'staffing_team','insurance_bonds','subcontracting_consortium','deliverables_scope',
 'sla_onsite','term_value','award_criteria','forms_signatures','submission',
 'ip_data_security','payment_tax']


def load(p,default=None):
    try:return json.loads(Path(p).read_text(encoding='utf-8',errors='replace'))
    except:return {} if default is None else default


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for cpath in root.rglob('candidate.json'):
        d=cpath.parent;c=load(cpath);m=load(d/'manifest.json');e=load(d/'evidence_quality.json');g=load(d/'gate_snippets.json')
        counts=(g.get('evidence_counts') or {}) if g.get('gate_readiness') else {}
        row={
          'candidate_id':c.get('candidate_id'),'sub_niche':c.get('historical_sub_niche') or 'UNKNOWN',
          'portal':c.get('portal'),'country':c.get('country'),'buyer':c.get('buyer'),'title':c.get('title'),
          'resolver_status':m.get('status'),'files':len(m.get('files') or []),
          'content_quality':e.get('content_quality'),'derived_status':e.get('derived_status'),
          'gate_ready':bool(e.get('gate_readiness')),'corpus_chars':g.get('corpus_chars') or 0,
          'gate_counts':{k:int(counts.get(k) or 0) for k in CANONICAL},
        }
        rows.append(row)
    rows.sort(key=lambda x:(x['sub_niche'],str(x['candidate_id'])))
    with (out/'candidate_dce_review.jsonl').open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    groups=defaultdict(list)
    for r in rows:groups[r['sub_niche']].append(r)
    niches={}
    for n,rs in sorted(groups.items()):
        ready=[r for r in rs if r['gate_ready']]
        d={'sample':len(rs),'resolver_statuses':dict(Counter(str(r['resolver_status'] or 'UNKNOWN') for r in rs)),
           'downloaded_candidates':sum(r['files']>0 for r in rs),'gate_ready':len(ready),
           'content_quality':dict(Counter(str(r['content_quality'] or 'UNKNOWN') for r in rs)),'gate_signal_prevalence':{}}
        for k in CANONICAL:
            d['gate_signal_prevalence'][k]={
              'candidates_with_signal':sum((r['gate_counts'].get(k) or 0)>0 for r in ready),
              'gate_ready_denominator':len(ready),
              'hit_rate_pct':round(100*sum((r['gate_counts'].get(k) or 0)>0 for r in ready)/len(ready),2) if ready else None,
              'total_snippets':sum(r['gate_counts'].get(k) or 0 for r in ready)}
        niches[n]=d
    summary={'contract':'HISTORICAL_SUBNICHE_DCE_GATE_RESEARCH_V1','total_candidates':len(rows),
      'resolver_statuses':dict(Counter(str(r['resolver_status'] or 'UNKNOWN') for r in rows)),
      'downloaded_candidates':sum(r['files']>0 for r in rows),'gate_ready_candidates':sum(r['gate_ready'] for r in rows),
      'subniches':niches,'final_verdict_allowed':False,
      'warning':'Gate signal prevalence means regex/snippet evidence exists in an authoritative gate-ready corpus; it is not a resolved mandatory-gate verdict.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    lines=['# Historical Sub-Niche DCE Reality Check v1','',f"Candidates: **{summary['total_candidates']}** · downloaded: **{summary['downloaded_candidates']}** · gate-ready authoritative corpora: **{summary['gate_ready_candidates']}**.",'','Historical research only. Gate hit rates below are evidence-signal prevalence, not pass/fail requirements.','','|Sub-niche|Sample|Downloaded|Gate-ready|Resolver statuses|','|---|---:|---:|---:|---|']
    for n,d in niches.items():lines.append(f"|{n}|{d['sample']}|{d['downloaded_candidates']}|{d['gate_ready']}|{', '.join(f'{k}:{v}' for k,v in d['resolver_statuses'].items())}|")
    lines += ['','## Gate signals among gate-ready DCEs','']
    for n,d in niches.items():
        if not d['gate_ready']:continue
        sig=[(k,v['hit_rate_pct'],v['total_snippets']) for k,v in d['gate_signal_prevalence'].items() if v['candidates_with_signal']]
        sig.sort(key=lambda x:(-x[1],x[0]))
        lines.append('### '+n)
        lines.append(', '.join(f"{k} {pct:.0f}%" for k,pct,_ in sig) if sig else 'No canonical gate signals extracted.')
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='subniches'},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
