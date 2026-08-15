#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def n(x):
    try:return float(x)
    except:return 0.0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--scorecard',required=True);ap.add_argument('--suppliers',required=True);ap.add_argument('--examples',required=True);ap.add_argument('--buyers',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    sc=read(a.scorecard);su=read(a.suppliers);ex=read(a.examples);bu=read(a.buyers)
    S=defaultdict(list);E=defaultdict(list);B=defaultdict(list)
    for r in su:S[r.get('svc_family','')].append(r)
    for r in ex:E[r.get('svc_family','')].append(r)
    for r in bu:B[r.get('svc_family','')].append(r)
    lines=['# USA Network / Intermediary — Semantic Business QA v3.2','',
           'Historical award evidence only. Supplier-shape heuristics do not prove subcontracting or current procurement access.','']
    verdict=[]
    for r in sc:
        fam=r.get('svc_family','');records=int(n(r.get('records')));buyers=int(n(r.get('buyers')));suppliers=int(n(r.get('suppliers')))
        repeat_share=n(r.get('repeat_org_or_network_award_share'));strong=n(r.get('strong_network_award_share'));ind=n(r.get('individual_ambiguous_award_share'));multi=int(n(r.get('repeat_3plus_buyer_suppliers')))
        if records>=100 and repeat_share>=.65 and multi>=10:route='PROMOTE_NETWORK_MODEL'
        elif records>=100 and repeat_share>=.45 and multi>=5:route='PROMOTE_CONDITIONALLY_NETWORK'
        elif records>=100 and repeat_share>=.30:route='NETWORK_PLAUSIBLE_HOLD_ECONOMICS'
        else:route='HOLD'
        verdict.append([fam,records,buyers,suppliers,strong,repeat_share,ind,multi,route])
        lines += [f'## {fam}',f'- awards **{records}** · buyers **{buyers}** · suppliers **{suppliers}**',f'- strong network-name share **{round(100*strong,1)}%** · strong+repeat-org **{round(100*repeat_share,1)}%** · individual/ambiguous **{round(100*ind,1)}%** · suppliers serving ≥3 buyers **{multi}**',f'- model routing: **{route}**','', '### Top supplier archetypes']
        for x in S[fam][:20]:lines.append(f"- {x.get('supplier')} — awards={x.get('awards')} buyers={x.get('buyers')} top-buyer-share={x.get('top_buyer_share')} shape={x.get('supplier_shape')}")
        lines += ['', '### Representative awards']
        for x in E[fam][:24]:lines.append(f"- {x.get('buyer')} | {x.get('supplier')} | {x.get('title')} | USD {x.get('award_value') or 'UNKNOWN'} | supplier_buyers={x.get('supplier_buyers')} | {x.get('supplier_shape')}")
        lines += ['', '### Repeat/high-volume buyers']
        for x in B[fam][:12]:lines.append(f"- {x.get('buyer')} — awards={x.get('awards')} suppliers={x.get('suppliers')} median={x.get('median_award')}")
        lines.append('')
    with (out/'qa_scorecard.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['svc_family','records','buyers','suppliers','strong_network_share','repeat_org_or_network_share','individual_ambiguous_share','suppliers_3plus_buyers','model_routing']);w.writerows(verdict)
    summary={'version':'HISTORICAL_US_NETWORK_INTERMEDIARY_QA_V3_2','families_reviewed':len(sc),'supplier_rows_reviewed':len(su),'example_rows_reviewed':len(ex),'buyer_rows_reviewed':len(bu),'routing_counts':{},'historical_only':True,'record_deletion':False}
    for r in verdict:summary['routing_counts'][r[-1]]=summary['routing_counts'].get(r[-1],0)+1
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8');(out/'QA_PACKET.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
