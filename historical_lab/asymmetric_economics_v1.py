#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(x):
    try:return float(x)
    except:return None

MODEL={
 'DATA_ENTRY_KEYING':('CORE',5,2),
 'EVIDENCE_LITERATURE_SYNTHESIS':('CORE_PLUS_PARTNER',5,3),
 'DATA_COLLECTION_RESEARCH':('CORE_OR_NETWORK',4,3),
 'DATA_VALIDATION_CODING':('CORE',5,2),
 'CONTENT_DATA_MIGRATION':('CORE_OR_PARTNER',4,3),
 'DATA_CLEANING_ENRICHMENT_MDM':('CORE_OR_PARTNER',5,3),
 'DATABASE_REGISTRY_OPERATIONS':('CORE',4,3),
 'OCR_TEXT_EXTRACTION':('CORE',5,2),
 'DESK_RESEARCH_BENCHMARKING':('CORE',5,2),
 'COURT_REPORTING':('NETWORK',3,3),
 'SIGN_LANGUAGE_INTERPRETATION':('NETWORK',2,4),
 'GENERAL_LANGUAGE_INTERPRETATION':('NETWORK',2,4),
 'REMOTE_LANGUAGE_INTERPRETATION':('NETWORK',3,3),
 'EXPERT_WITNESS':('NETWORK_PARTNER',2,5),
 'LITIGATION_SUPPORT':('PARTNER',2,5),
 'INDEPENDENT_REVIEW':('NETWORK_PARTNER',4,4),
 'POLICY_PROGRAM_EVALUATION':('NETWORK_PARTNER',4,4),
 'PROJECT_PROGRAM_ASSURANCE':('PARTNER',3,5),
 'RESEARCH_MONITORING_EVALUATION':('NETWORK_PARTNER',4,4),
}

def asym(model_key,records,buyers,top_share,bidders):
    model,compression,friction=MODEL.get(model_key,('OPEN',2,4))
    frag=0 if top_share is None else max(0,min(1,1-top_share))*5
    breadth=min(5,math.log1p(max(0,buyers))*1.15)
    recurrence=min(5,math.log1p(max(0,records))*0.9)
    comp=2.5 if bidders is None else min(5,max(0,bidders))
    # Heuristic is intentionally coarse and exposed as model output.
    score=round(10*(0.30*(compression/5)+0.22*(frag/5)+0.18*(breadth/5)+0.15*(recurrence/5)+0.05*(comp/5)+0.10*((6-friction)/5)),1)
    return model,compression,friction,score

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--global-matrix',required=True);ap.add_argument('--usa-score',required=True);ap.add_argument('--au-matrix',required=True);ap.add_argument('--broker',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    gm=read(a.global_matrix);us=read(a.usa_score);au=read(a.au_matrix);br=read(a.broker)
    rows=[]
    for r in gm:
        if r.get('purity_class')!='PURE_DIGITAL_OR_REMOTE_SERVICE':continue
        fam=r.get('info_family');records=num(r.get('records')) or 0;buyers=num(r.get('buyers')) or 0;share=num(r.get('top_supplier_share'));bidders=num(r.get('median_bidders'));model,comp,fric,score=asym(fam,records,buyers,share,bidders)
        rows.append({'source':'GLOBAL_CORE','lane':fam,'model':model,'country':r.get('country'),'currency':r.get('currency'),'records':records,'buyers':buyers,'repeat_buyers':num(r.get('repeat_buyers')),'suppliers':num(r.get('suppliers')),'p25_value':num(r.get('p25_value')),'median_value':num(r.get('median_value')),'p75_value':num(r.get('p75_value')),'median_bidders':bidders,'top_supplier_share':share,'compression_hypothesis_1to5':comp,'friction_hypothesis_1to5':fric,'asymmetry_routing_score_0to10':score})
    for r in us:
        fam=r.get('svc_family');records=num(r.get('records')) or 0;buyers=num(r.get('buyers')) or 0;share=num(r.get('top_supplier_share'));model,comp,fric,score=asym(fam,records,buyers,share,None)
        rows.append({'source':'USASPENDING','lane':fam,'model':model,'country':'USA','currency':'USD','records':records,'buyers':buyers,'repeat_buyers':None,'suppliers':num(r.get('suppliers')),'p25_value':num(r.get('p25_award')),'median_value':num(r.get('median_award')),'p75_value':num(r.get('p75_award')),'median_bidders':None,'top_supplier_share':share,'compression_hypothesis_1to5':comp,'friction_hypothesis_1to5':fric,'asymmetry_routing_score_0to10':score})
    for r in au:
        fam=r.get('review_family');risk=r.get('delivery_risk');
        if risk!='REMOTE_ANALYTICAL_PLAUSIBLE':continue
        records=num(r.get('records')) or 0;buyers=num(r.get('buyers')) or 0;share=num(r.get('top_supplier_share'));model,comp,fric,score=asym(fam,records,buyers,share,None)
        rows.append({'source':'AUSTENDER','lane':fam,'model':model,'country':'Australia','currency':r.get('currency') or 'AUD','records':records,'buyers':buyers,'repeat_buyers':num(r.get('repeat_buyers')),'suppliers':num(r.get('supplier_keys')),'p25_value':num(r.get('p25_value')),'median_value':num(r.get('median_value')),'p75_value':num(r.get('p75_value')),'median_bidders':None,'top_supplier_share':share,'compression_hypothesis_1to5':comp,'friction_hypothesis_1to5':fric,'asymmetry_routing_score_0to10':score})
    fields=['source','lane','model','country','currency','records','buyers','repeat_buyers','suppliers','p25_value','median_value','p75_value','median_bidders','top_supplier_share','compression_hypothesis_1to5','friction_hypothesis_1to5','asymmetry_routing_score_0to10']
    with (out/'economic_profiles.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    # Broker clusters are not FX/currency-normalized in the current derived asset; retain structural evidence only.
    broker=[]
    for r in br:
        broker.append({'archetype':r.get('archetype'),'friction':r.get('friction'),'economic_score':num(r.get('economic_score')),'records':num(r.get('records')),'buyers':num(r.get('buyers')),'suppliers':num(r.get('suppliers')),'top_supplier_share':num(r.get('top_supplier_share')),'median_bidders':num(r.get('median_bidders')),'median_value_native_unlabelled':num(r.get('median_value')),'native_code':r.get('native_code'),'example_titles':r.get('example_titles')})
    with (out/'broker_structural_profiles.csv').open('w',encoding='utf-8',newline='') as f:
        fields2=list(broker[0].keys()) if broker else ['archetype'];w=csv.DictWriter(f,fieldnames=fields2);w.writeheader();w.writerows(broker)
    summary={'version':'HISTORICAL_ASYMMETRIC_ECONOMICS_V1','profile_rows':len(rows),'broker_cluster_rows':len(broker),'historical_only':True,'currency_mixing':False,'score_role':'MODEL_ROUTING_HEURISTIC_NOT_MARGIN_ESTIMATE','warning':'Compression/friction/asymmetry scores are explicit model hypotheses. Historical values remain within native country/currency rows and are not FX-normalized. No gross margin is inferred.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Historical Asymmetric Economics v1','',f'- empirical lane×country/currency profiles **{len(rows)}**',f'- broker structural clusters **{len(broker)}**','', '**No margin is invented.** Historical values stay in native currencies. Compression/friction scores are model hypotheses and are shown separately from facts.','']
    for src in ['GLOBAL_CORE','USASPENDING','AUSTENDER']:
        lines += [f'## {src}','']
        for r in sorted([x for x in rows if x['source']==src],key=lambda x:x['asymmetry_routing_score_0to10'],reverse=True):
            lines.append(f"- **{r['lane']}** · {r['country']} {r['currency']} · records={int(r['records'])} buyers={int(r['buyers'])} suppliers={int(r['suppliers']) if r['suppliers'] is not None else 'UNKNOWN'} · p25={r['p25_value']} median={r['median_value']} p75={r['p75_value']} · bidders={r['median_bidders']} top_share={r['top_supplier_share']} · model={r['model']} · compression={r['compression_hypothesis_1to5']}/5 friction={r['friction_hypothesis_1to5']}/5 · routing={r['asymmetry_routing_score_0to10']}/10")
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
