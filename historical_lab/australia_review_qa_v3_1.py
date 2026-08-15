#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from collections import defaultdict
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def n(x):
    try:return float(x)
    except:return 0.0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--examples',required=True);ap.add_argument('--winners',required=True);ap.add_argument('--matrix',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    ex=read(a.examples);wi=read(a.winners);ma=read(a.matrix)
    E=defaultdict(list);W=defaultdict(list);M=defaultdict(list)
    for r in ex:E[(r.get('review_family',''),r.get('delivery_risk',''))].append(r)
    for r in wi:W[(r.get('review_family',''),r.get('delivery_risk',''))].append(r)
    for r in ma:M[(r.get('review_family',''),r.get('delivery_risk',''))].append(r)
    keys=sorted(set(E)|set(W)|set(M))
    lines=['# Australia Review / Evaluation — Semantic Business QA v3.1','',
           'Historical evidence only. The heuristics below are model-routing signals, not eligibility findings.','']
    verdict_rows=[]
    for key in keys:
        fam,risk=key; rows=E[key]
        text=' '.join((r.get('title','')+' '+r.get('description_excerpt','')).lower() for r in rows)
        field=sum(bool(re.search(r'\b(interview|focus group|stakeholder engagement|community engagement|workshop|survey|fieldwork|field work|site visit|consultation)\b',(r.get('title','')+' '+r.get('description_excerpt','')).lower())) for r in rows)
        credential=sum(bool(re.search(r'\b(engineer|engineering|medical|clinical|legal|lawyer|actuar|registered|licensed|licenced|certified|clearance|accredit|audit standard|accounting)\b',(r.get('title','')+' '+r.get('description_excerpt','')).lower())) for r in rows)
        report=sum(bool(re.search(r'\b(report|findings|recommendations|review|evaluation|assessment|analysis|briefing|framework|methodology)\b',(r.get('title','')+' '+r.get('description_excerpt','')).lower())) for r in rows)
        top=W[key][:20]
        multi=sum(1 for r in top if n(r.get('buyers'))>=2)
        top5=sum(n(r.get('supplier_share')) for r in top[:5])
        if risk!='REMOTE_ANALYTICAL_PLAUSIBLE': verdict='PARTNER_OR_HOLD'
        elif credential>=max(2,len(rows)//4): verdict='PARTNER_LEAN_POSSIBLE'
        elif field>=max(3,len(rows)//3): verdict='NETWORK_RESEARCH_OR_HOLD'
        elif report>=max(3,len(rows)//2) and multi>=3: verdict='PROMOTE_CONDITIONALLY_NETWORK'
        elif report>=max(3,len(rows)//2): verdict='PROMOTE_CONDITIONALLY_CORE_PARTNER'
        else: verdict='HOLD_FOR_MORE_QA'
        verdict_rows.append([fam,risk,len(rows),field,credential,report,multi,top5,verdict])
        lines += [f'## {fam} → {risk}',f'- sampled examples **{len(rows)}** · field/stakeholder cues **{field}** · credential cues **{credential}** · report/analysis cues **{report}**',f'- top-20 winners serving ≥2 buyers **{multi}** · top-5 sampled supplier share sum **{round(100*top5,1)}%**',f'- model routing: **{verdict}**','', '### Representative evidence']
        for r in rows[:16]:
            desc=(r.get('description_excerpt') or '').replace('\n',' ')[:600]
            lines.append(f"- {r.get('buyer')} | {r.get('supplier')} | {r.get('title')} | AUD {r.get('award_value') or 'UNKNOWN'} | signal={r.get('signal_source')} :: {desc}")
        lines += ['', '### Repeat/top winner evidence']
        for r in top[:15]:lines.append(f"- {r.get('supplier')} — awards={r.get('awards')} buyers={r.get('buyers')} share={r.get('supplier_share')}")
        lines.append('')
    with (out/'qa_scorecard.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['review_family','delivery_risk','sample_examples','field_cues','credential_cues','report_analysis_cues','top20_multi_buyer_winners','top5_share_sum','model_routing']);w.writerows(verdict_rows)
    summary={'version':'HISTORICAL_AU_REVIEW_EVALUATION_QA_V3_1','groups_reviewed':len(keys),'example_rows_reviewed':len(ex),'winner_rows_reviewed':len(wi),'routing_counts':dict((v,sum(1 for r in verdict_rows if r[-1]==v)) for v in sorted(set(r[-1] for r in verdict_rows))),'historical_only':True,'record_deletion':False,'warning':'Model routing is based on representative stored evidence and requires further targeted QA for any promoted lane.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'QA_PACKET.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
