#!/usr/bin/env python3
from __future__ import annotations

"""Build an audited SPM market-hunting matrix from Micro-Niche v2 Precision.

The matrix is a historical prioritisation artifact, not a live bid verdict.
Only manually promoted/held cohorts are encoded here. Unknowns remain explicit.
"""

import argparse
import csv
import json
from pathlib import Path


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def source_of(r):
    return r.get("warehouse_source") or r.get("source") or ""


def cohort_key(r):
    return (r.get("micro_niche", ""), source_of(r), r.get("country", ""), r.get("route", ""), r.get("currency", ""))


CONFIG = [
    # TIER A — manually promoted for live hunting.
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="BROKER", niche="Commercial printing / print production", source="Quebec", country="CANADA - QUEBEC", route="OPEN_PUBLIC", currency="CAD", rationale="Clean printing sample; bidder median 2; fragmented observed winners.", blockers="locality/delivery; sustainable paper/ink; proofs/samples; financial capacity; subcontracting; registration/tax"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="CORE_DIGITAL", niche="Website maintenance / hosting / support", source="Germany", country="GERMANY", route="OPEN_PUBLIC", currency="EUR", rationale="Clean recurring website care/hosting/support titles; bidder median 3.", blockers="references; CMS/stack; SLA/on-call; accessibility/security; hosting/data location; staffing"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="CORE_CREATIVE", niche="Graphic design / DTP / visual identity", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Broad buyer base and recurring institutional design/layout demand.", blockers="portfolio/references; source files; print bundles; accessibility; brand/IP; response capacity"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="BROKER", niche="Commercial printing / print production", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Large recurring buyer base; brokerable production economics.", blockers="exact volumes/specs; routing; delivery cadence; environmental labels; samples; working capital; subcontracting"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="CORE_LANGUAGE", niche="Translation services", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Clean written/interpreting demand after equipment false-positive hardening.", blockers="translator credentials; native-language rules; interpreting/on-site; confidentiality; turnaround; references"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="AI_HUMAN_LANGUAGE", niche="Transcription / speech-to-text", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Clean stenotypy/retranscription/minutes cohort; high AI leverage with human QA.", blockers="human stenographer requirement; accuracy; confidentiality; on-site presence; turnaround; data security"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="CORE_DIGITAL", niche="Website maintenance / hosting / support", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Recurring public web maintenance/hosting lane with precise title semantics.", blockers="references; stack; SLA; hosting/data; accessibility; security; staffing"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="CORE_DIGITAL", niche="Website design / redesign / development", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Clean refonte/creation/development sample; institutional web is lean-build compatible.", blockers="references; CMS choice; accessibility; migration; content volume; hosting; maintenance; IP/source code"),
    dict(tier="A_HUNT_NOW", motion="OPEN_BID", model="CORE_LANGUAGE", niche="Translation services", source="Canada federal", country="CANADA", route="OPEN_PUBLIC", currency="CAD", rationale="Semantically clean federal translation lane; modest prior because bidder evidence is absent.", blockers="security clearance; official-language credentials; Canadian presence; references; confidentiality; standing-offer rules"),

    # TIER B — attractive but not fully promoted or has concentration/delivery ambiguity.
    dict(tier="B_WATCH", motion="OPEN_BID", model="BROKER", niche="Promotional merchandise / branded goods", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Clean brokerable branded-goods demand; existing promotional-merchandise prior remains active.", blockers="samples; eco/textile labels; delivery; stock; personalization; working capital; framework terms"),
    dict(tier="B_WATCH", motion="OPEN_BID", model="BROKER", niche="Mailing / fulfilment / routing", source="France", country="FRANCE", route="OPEN_PUBLIC", currency="EUR", rationale="Clean routing/mail fulfilment titles and many buyers; often pairs naturally with print brokerage.", blockers="postal rates; address data; GDPR; physical handling; SLA; storage; working capital"),
    dict(tier="B_HOLD_QA", motion="OPEN_BID", model="RESEARCH_SERVICE", niche="Market research / surveys / polling", source="Ireland", country="IRELAND", route="OPEN_PUBLIC", currency="EUR", rationale="Quantitatively attractive but archaeological survey contamination persists; broad live bonus disabled.", blockers="semantic fit first; research methodology; specialist domain; panel/sample; fieldwork; references"),
    dict(tier="B_HOLD_MODEL", motion="OPEN_BID", model="RESEARCH_SERVICE", niche="Market research / surveys / polling", source="Quebec", country="CANADA - QUEBEC", route="OPEN_PUBLIC", currency="CAD", rationale="Low observed competition but scopes range into financial/risk analysis; delivery model not validated.", blockers="specialist research; methodology; French/local fieldwork; professional expertise; references"),
    dict(tier="B_HOLD_CONCENTRATION", motion="OPEN_BID", model="SAAS_BROKER_OR_SERVICE", niche="Media / press monitoring", source="Ireland", country="IRELAND", route="OPEN_PUBLIC", currency="EUR", rationale="Semantically clean but observed winner concentration is high; likely vendor/platform advantage.", blockers="platform/IP; monitoring coverage; licensing; reseller rights; data sources; concentration"),

    # DIRECT BUYER — demand intelligence / outbound, never open-bid ease.
    dict(tier="D_DIRECT_BUYER", motion="DIRECT_BUYER", model="AI_HUMAN_LANGUAGE", niche="Transcription / speech-to-text", source="Quebec", country="CANADA - QUEBEC", route="DIRECT_NONCOMPETITIVE", currency="CAD", rationale="Very strong recurring justice-sector demand; useful for buyer mapping/outbound only.", blockers="direct-award route; stenographer credentials; legal confidentiality; local presence"),
    dict(tier="D_DIRECT_BUYER", motion="DIRECT_BUYER", model="CORE_LANGUAGE", niche="Translation services", source="Quebec", country="CANADA - QUEBEC", route="DIRECT_NONCOMPETITIVE", currency="CAD", rationale="Large repeat justice-sector demand; not evidence of easy open competition.", blockers="direct-award route; court interpreter credentials; language coverage; confidentiality; local presence"),
    dict(tier="D_DIRECT_BUYER", motion="DIRECT_BUYER", model="CORE_CREATIVE", niche="Graphic design / DTP / visual identity", source="Quebec", country="CANADA - QUEBEC", route="DIRECT_NONCOMPETITIVE", currency="CAD", rationale="Recurring small creative mandates; useful for relationship/outbound targeting.", blockers="direct-award route; local references; portfolio; language; source files"),
    dict(tier="D_DIRECT_BUYER", motion="DIRECT_BUYER", model="BROKER", niche="Software licence renewal / licensing", source="Quebec", country="CANADA - QUEBEC", route="DIRECT_NONCOMPETITIVE", currency="CAD", rationale="Recurring licence demand; useful for reseller/vendor relationship intelligence only.", blockers="authorized reseller status; vendor partner tier; incumbent lock-in; direct-award route"),
]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dir',required=True)
    ap.add_argument('--out',required=True)
    a=ap.parse_args(); src=Path(a.dir); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    all_rank=read_csv(src/'micro_niche_rank.csv')
    repeat=read_csv(src/'repeat_buyers_micro_niche.csv')
    winners=read_csv(src/'top_winners_micro_niche.csv')
    rank_by={cohort_key(r):r for r in all_rank}
    rep_by={}; win_by={}
    for r in repeat: rep_by.setdefault(cohort_key(r),[]).append(r)
    for r in winners: win_by.setdefault(cohort_key(r),[]).append(r)

    result=[]; missing=[]
    for c in CONFIG:
        k=(c['niche'],c['source'],c['country'],c['route'],c['currency'])
        r=rank_by.get(k)
        if not r:
            missing.append(k); continue
        reps=sorted(rep_by.get(k,[]),key=lambda x:float(x.get('procurements') or 0),reverse=True)[:5]
        wins=sorted(win_by.get(k,[]),key=lambda x:float(x.get('fractional_awards') or 0),reverse=True)[:5]
        result.append({
            **c,
            'records':r.get('records'), 'buyers':r.get('buyers'), 'repeat_buyers':r.get('repeat_buyers'),
            'repeat_buyer_rate_pct':r.get('repeat_buyer_rate'),
            'p25_award_value':r.get('p25_award_value'), 'median_award_value':r.get('median_award_value'), 'p75_award_value':r.get('p75_award_value'),
            'bidder_rows':r.get('bidder_rows'), 'median_bidders':r.get('median_bidders'), 'single_bid_pct':r.get('single_bid_pct'),
            'supplier_count':r.get('supplier_count'), 'top_supplier_share_pct':r.get('top_supplier_share_pct'), 'hhi':r.get('hhi'),
            'historical_spm_score':r.get('historical_spm_score'),
            'top_repeat_buyers':[{'buyer':x.get('buyer'),'procurements':x.get('procurements')} for x in reps],
            'top_winners':[{'supplier':x.get('supplier'),'fractional_awards':x.get('fractional_awards'),'share_pct':x.get('share_pct')} for x in wins],
        })

    tier_order={'A_HUNT_NOW':0,'B_WATCH':1,'B_HOLD_QA':2,'B_HOLD_MODEL':2,'B_HOLD_CONCENTRATION':2,'D_DIRECT_BUYER':3}
    result.sort(key=lambda r:(tier_order.get(r['tier'],9),-float(r.get('historical_spm_score') or 0)))

    headers=['tier','motion','model','niche','source','country','route','currency','records','buyers','repeat_buyers','repeat_buyer_rate_pct','p25_award_value','median_award_value','p75_award_value','bidder_rows','median_bidders','single_bid_pct','supplier_count','top_supplier_share_pct','hhi','historical_spm_score','rationale','blockers','top_repeat_buyers','top_winners']
    with (out/'SPM_ACTION_MATRIX_V1.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=headers); w.writeheader()
        for r in result:
            q=dict(r); q['top_repeat_buyers']=json.dumps(q['top_repeat_buyers'],ensure_ascii=False); q['top_winners']=json.dumps(q['top_winners'],ensure_ascii=False); w.writerow({k:q.get(k,'') for k in headers})
    (out/'SPM_ACTION_MATRIX_V1.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')

    md=['# SPM Historical Action Matrix v1','',
        'Source: audited Micro-Niche v2 Precision over canonical Global Core v4 notice-first facts. Historical market prior only; live DCE remains mandatory.','',
        '## Tier A — hunt live now','',
        '|Market|Model|Records|Buyers|Repeat buyers|Median award|Median bidders|Top supplier share|Hist. score|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in result:
        if r['tier']!='A_HUNT_NOW': continue
        market=f"{r['country']} — {r['niche']}"
        md.append(f"|{market}|{r['model']}|{r['records']}|{r['buyers']}|{r['repeat_buyers']}|{r['currency']} {r.get('median_award_value') or 'UNKNOWN'}|{r.get('median_bidders') or 'UNKNOWN'}|{r.get('top_supplier_share_pct') or 'UNKNOWN'}%|{r['historical_spm_score']}|")
    md += ['', '## Watch / hold', '']
    for r in result:
        if r['tier'].startswith('B_'):
            md += [f"### {r['tier']} — {r['country']} — {r['niche']}", f"{r['rationale']}  ", f"DCE watchouts: {r['blockers']}", '']
    md += ['## Direct-buyer intelligence only','']
    for r in result:
        if r['tier']=='D_DIRECT_BUYER':
            buyers=', '.join(f"{x['buyer']} ({x['procurements']})" for x in r['top_repeat_buyers'][:3]) or 'UNKNOWN'
            md += [f"- **{r['country']} — {r['niche']}**: median historical award {r['currency']} {r.get('median_award_value') or 'UNKNOWN'}; top repeat buyers: {buyers}."]
    md += ['', '## Safety', '', '- `A_HUNT_NOW` means prioritise live discovery/DCE retrieval, not bid automatically.', '- Direct/noncompetitive history is never converted into open-bid competition evidence.', '- Missing bidder/value/reference/eligibility evidence remains UNKNOWN.', '- Partner/reseller, turnover, references, insurance, staffing, subcontracting, localization, deadline and submission gates are resolved only from authoritative live documents.']
    (out/'SPM_ACTION_MATRIX_V1.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    (out/'manifest.json').write_text(json.dumps({'contract':'SPM_HISTORICAL_ACTION_MATRIX_V1','rows':len(result),'missing_config_cohorts':[list(x) for x in missing],'source_release':'market-intelligence-micro-niche-v2-precision','historical_only':True,'satisfies_dce_gates':False},indent=2),encoding='utf-8')
    print(json.dumps({'rows':len(result),'missing':len(missing),'missing_keys':missing},indent=2))
    if missing: raise SystemExit(2)

if __name__=='__main__': main()
