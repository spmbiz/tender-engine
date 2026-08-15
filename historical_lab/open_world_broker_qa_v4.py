#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from collections import defaultdict
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(x):
    try:return float(x)
    except:return 0.0

def friction(ar,text):
    t=(text or '').lower()
    if ar in {'OFFICE_STATIONERY','TONER_PRINTER_CONSUMABLES','SPORT_RECREATION_MUSICAL'}:return 'LOW_TO_MEDIUM'
    if ar=='OFFICE_IT_EQUIPMENT':
        return 'HIGH_IMPLEMENTATION' if re.search(r'install|integration|инсталац|интеграц|system|система',t) else 'MEDIUM_RESELL'
    if ar in {'FURNITURE_MISC_MANUFACTURED','FURNITURE_SUPPLY_INSTALL','SIGNAGE'}:return 'MEDIUM_LOCAL_INSTALL_LOGISTICS'
    if ar in {'FOOD_SUPPLY','FOOD_BEVERAGE'}:return 'HIGH_LOGISTICS_PERISHABLE_MARGIN'
    if ar=='LAB_REAGENTS_CONSUMABLES':return 'HIGH_REGULATORY_COMPATIBILITY'
    if ar in {'TELECOM_ELECTRONICS','ELECTRICAL_EQUIPMENT'}:return 'MEDIUM_HIGH_TECH_INSTALL'
    if ar in {'WORKWEAR_UNIFORMS','PROMOTIONAL_MERCH'}:return 'MEDIUM_SOURCING_SAMPLE_LOGISTICS'
    return 'MEDIUM_UNKNOWN'
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=[r for r in read(a.input) if r.get('routing')=='BROKER_RESELL_CANDIDATE']
    outrows=[];groups=defaultdict(list)
    for r in rows:
        fr=friction(r.get('archetype',''),r.get('example_titles',''));r=dict(r);r['friction']=fr;groups[(r.get('archetype',''),fr)].append(r);outrows.append(r)
    with (out/'broker_candidates_qa.csv').open('w',encoding='utf-8',newline='') as f:
        fields=list(outrows[0].keys()) if outrows else ['archetype','friction'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(outrows)
    summary={'version':'HISTORICAL_OPEN_WORLD_BROKER_QA_V4','broker_clusters_reviewed':len(rows),'friction_counts':{},'archetype_counts':{},'historical_only':True,'record_deletion':False,'warning':'Friction is a model heuristic. Actual reseller authorization, warranties, delivery, credit terms, regulatory requirements and margins remain unknown.'}
    for r in outrows:summary['friction_counts'][r['friction']]=summary['friction_counts'].get(r['friction'],0)+1;summary['archetype_counts'][r['archetype']]=summary['archetype_counts'].get(r['archetype'],0)+1
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Open-World Broker / Reseller QA v4','',f'- broker/resell clusters reviewed **{len(rows)}**','', 'Historical discovery only. The objective is to separate easy sourcing arbitrage from logistics/regulatory/installation-heavy distribution.','']
    order=['LOW_TO_MEDIUM','MEDIUM_RESELL','MEDIUM_SOURCING_SAMPLE_LOGISTICS','MEDIUM_LOCAL_INSTALL_LOGISTICS','MEDIUM_HIGH_TECH_INSTALL','HIGH_IMPLEMENTATION','HIGH_LOGISTICS_PERISHABLE_MARGIN','HIGH_REGULATORY_COMPATIBILITY','MEDIUM_UNKNOWN']
    for fr in order:
        subset=[r for r in outrows if r['friction']==fr]
        if not subset:continue
        lines += [f'## {fr}',f'- clusters **{len(subset)}**','']
        for r in sorted(subset,key=lambda x:num(x.get('economic_score')),reverse=True)[:30]:
            lines.append(f"- score {r.get('economic_score')} · {r.get('archetype')} · {r.get('source')} · code={r.get('native_code')} · records={r.get('records')} buyers={r.get('buyers')} suppliers={r.get('suppliers')} share={r.get('top_supplier_share')} bidders={r.get('median_bidders')} median={r.get('median_value')} :: {r.get('example_titles')}")
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
