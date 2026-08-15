#!/usr/bin/env python3
from __future__ import annotations

"""Apply DCE-reality-check refinements without turning historical gates into verdicts."""
import argparse,json
from datetime import datetime,timezone
from pathlib import Path


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--priors',default='control/historical_market_priors.json');ap.add_argument('--out',default='control/historical_market_priors.json');a=ap.parse_args()
    data=json.loads(Path(a.priors).read_text(encoding='utf-8'))
    assert data.get('contract')=='TENDER_MARKET_BRAIN_PRIORS_V1' and data.get('status')=='READY'
    rules=list(data.get('lane_rules') or [])
    target=None
    for r in rules:
        if r.get('country')=='FRANCE' and r.get('lane')=='Website / CMS build or redesign':target=r;break
    if target is None:raise SystemExit('France web-build prior missing')
    target['match_field']='title'
    target['sample_size']=66;target['historical_score']=79.14;target['priority_bonus']=4;target['decision']='PROMOTE_CORE'
    target['patterns']=[
      r'(?:refonte|cr[eé]ation|conception|d[eé]veloppement|relaunch|redesign).{0,90}(?:site internet|site web|website|portail web)',
      r'(?:site internet|site web|website|portail web).{0,90}(?:refonte|cr[eé]ation|conception|d[eé]veloppement|relaunch|redesign)',
      r'(?:wordpress|drupal|joomla).{0,90}(?:site|website|cms|portail)']
    target['negative_patterns']=[
      r'portal crane',r'security portal',r'x-ray',r'medical',r'hardware',
      r'assistance [àa] ma[iî]trise d.?ouvrage',r'\bamo\b.{0,50}(?:site|web|refonte)',r'mission.{0,30}ma[iî]trise d.?ouvrage']
    data['historical_dce_reality_check_v1']={
      'authority':'control/historical_subniche_dce_review_v1/REPORT.md',
      'evidence_pack':'control/historical_gate_evidence_pack_v1/index.json',
      'sampled_candidates':43,'downloaded_gate_ready':17,
      'retrieval_refinement':['France web build: exclude AMO/owner-assistance scopes from implementation prior'],
      'gate_watchlist':{
        'FRANCE|Website support / hosting':['references/experience','stack-specific certifications where stated','submission','security/IP/SLA where stated'],
        'FRANCE|Website redesign / development':['references/experience','turnover declaration where stated','staffing where stated','tax/social attestations','exclude AMO from build motion'],
        'FRANCE|Publication layout / DTP':['turnover declaration','professional insurance','references over recent years','staffing/equipment','award quality weighting'],
        'FRANCE|Written translation':['references/qualifications where stated','technical-quality weighting','language/submission','framework min/max volumes'],
        'FRANCE|Transcription':['references/qualifications or equivalent proof where stated','quality certification/authorization where stated','confidentiality/accuracy/turnaround to verify'],
        'FRANCE|Promotional goods':['reserved-participation check','turnover/references where stated','RSE/product quality/marking','working capital/logistics'],
        'FRANCE|Municipal magazine printing':['quantities/frequency','delivery','payment delay','grouping/subcontracting','paper/print specifications from DCE']},
      'safety':'Watchlist is retrieval/review guidance only; each live DCE must resolve the actual mandatory wording.'}
    data['generated_at']=datetime.now(timezone.utc).isoformat()
    Path(a.out).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

if __name__=='__main__':main()
