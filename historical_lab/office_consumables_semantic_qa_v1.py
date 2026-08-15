#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from collections import defaultdict
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(x):
    try:return float(x)
    except:return None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--candidates',required=True);ap.add_argument('--examples',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    cand=read(a.candidates);ex=read(a.examples);E=defaultdict(list)
    for r in ex:E[(r.get('goods_family',''),r.get('country',''),r.get('currency',''),r.get('brand_policy',''),r.get('fulfillment_shape',''))].append(r)
    # Inspect the strongest structural cohorts, not only one country.
    cand=sorted(cand,key=lambda r:num(r.get('broker_routing_score')) or 0,reverse=True)[:30]
    rows=[];lines=['# Office Consumables — Semantic QA v1','', 'Historical examples only. Brand flexibility remains UNKNOWN unless explicitly stated.','']
    for c in cand:
        key=(c.get('goods_family',''),c.get('country',''),c.get('currency',''),c.get('brand_policy',''),c.get('fulfillment_shape',''))
        xs=E.get(key,[])
        pure=service=furniture=printing_service=hardware_mix=0
        for x in xs:
            t=((x.get('title') or '')+' '+(x.get('scope_excerpt') or '')).lower()
            if re.search(r'\b(managed print|print management|maintenance|repair|rental|leasing|lease|installation|integration|fleet management)\b',t):service+=1
            if re.search(r'\b(furniture|chair|desk|cabinet|mobilier|möbel)\b',t):furniture+=1
            if re.search(r'\b(printing services|print services|impression de documents|druckdienst|brochure printing|publication printing)\b',t):printing_service+=1
            if re.search(r'\b(computer|laptop|server|network equipment|hardware supply|ordinateur|rechner|notebook)\b',t):hardware_mix+=1
            if not any([re.search(r'\b(managed print|print management|maintenance|repair|rental|leasing|lease|installation|integration|fleet management)\b',t),re.search(r'\b(furniture|chair|desk|cabinet|mobilier|möbel)\b',t),re.search(r'\b(printing services|print services|impression de documents|druckdienst|brochure printing|publication printing)\b',t)]):pure+=1
        n=len(xs);contam=service+furniture+printing_service
        share=num(c.get('top_supplier_share'));buyers=num(c.get('buyers')) or 0;records=num(c.get('records')) or 0
        if n>=5 and contam/n<=.20 and (share is None or share<.45) and buyers>=8:route='PROMOTE_MARGIN_TEST'
        elif n>=3 and contam/n<=.35 and (share is None or share<.60):route='PROMOTE_CONDITIONALLY'
        else:route='HOLD_OR_MORE_QA'
        rows.append([*key,c.get('records'),c.get('buyers'),c.get('suppliers'),c.get('median_value'),c.get('median_bidders'),c.get('top_supplier_share'),c.get('broker_routing_score'),n,pure,service,furniture,printing_service,hardware_mix,route])
        lines += [f"## {key[0]} · {key[1]} {key[2]} · {key[3]}",f"- records **{c.get('records')}** · buyers **{c.get('buyers')}** · suppliers **{c.get('suppliers')}** · median **{c.get('median_value')} {c.get('currency')}** · bidders **{c.get('median_bidders')}** · top share **{c.get('top_supplier_share')}**",f'- stored examples reviewed **{n}** · clean-looking **{pure}** · service/install cues **{service}** · furniture cues **{furniture}** · print-service cues **{printing_service}** · hardware-mix cues **{hardware_mix}**',f'- routing: **{route}**','']
        for x in xs[:12]:
            lines.append(f"- {x.get('buyer')} | {x.get('title')} | value={x.get('reference_value')} {x.get('currency')} | bidders={x.get('bidder_count')} | recurrence={x.get('recurrence_signal')}")
        lines.append('')
    header=['goods_family','country','currency','brand_policy','fulfillment_shape','records','buyers','suppliers','median_value','median_bidders','top_supplier_share','broker_routing_score','sample_examples','clean_examples','service_install_cues','furniture_cues','print_service_cues','hardware_mix_cues','model_routing']
    with (out/'qa_scorecard.csv').open('w',encoding='utf-8',newline='') as f:w=csv.writer(f);w.writerow(header);w.writerows(rows)
    summary={'version':'HISTORICAL_OFFICE_CONSUMABLES_SEMANTIC_QA_V1','candidate_cohorts_reviewed':len(rows),'routing_counts':{},'historical_only':True,'record_deletion':False,'warning':'Example QA is representative, not exhaustive. BRAND_POLICY_UNSPECIFIED never implies compatible/remanufactured products are allowed.'}
    for r in rows:summary['routing_counts'][r[-1]]=summary['routing_counts'].get(r[-1],0)+1
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8');(out/'QA_PACKET.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
