#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from collections import defaultdict
from pathlib import Path

NAICS3={
 '311':'FOOD_MANUFACTURING','312':'BEVERAGE_TOBACCO','313':'TEXTILE_MILLS','314':'TEXTILE_PRODUCTS','315':'APPAREL','316':'LEATHER_PRODUCTS','321':'WOOD_PRODUCTS','322':'PAPER_PRODUCTS','323':'PRINTING_RELATED','324':'PETROLEUM_COAL','325':'CHEMICALS','326':'PLASTICS_RUBBER','327':'NONMETALLIC_MINERALS','331':'PRIMARY_METALS','332':'FABRICATED_METAL','333':'MACHINERY','334':'COMPUTER_ELECTRONICS','335':'ELECTRICAL_EQUIPMENT','336':'TRANSPORT_EQUIPMENT','337':'FURNITURE','339':'MISC_MANUFACTURING'}

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(x):
    try:return float(x)
    except:return 0.0

def shape(t):
    x=(t or '').lower()
    if re.search(r'\b(bolt|screw|fastener|nut\b|washer|bearing|gasket|seal\b|hose|filter|belt\b|cable|connector|fuse|battery|batteries|valve|fitting|clamp|spring|brush|blade|drill bit|abrasive|o-ring|oring)\b',x):return 'STANDARDIZED_MRO_CONSUMABLE_SIGNAL'
    if re.search(r'\b(label|labels|envelope|packaging|box|boxes|carton|paper product|printed form|printing|booklet|brochure|signage|signs)\b',x):return 'PRINT_PACKAGING_SIGNAL'
    if re.search(r'\b(uniform|apparel|shirt|jacket|glove|footwear|boot|textile|fabric|linen|towel)\b',x):return 'TEXTILE_APPAREL_SIGNAL'
    if re.search(r'\b(furniture|desk|chair|shelving|cabinet|locker|table)\b',x):return 'FURNITURE_SIGNAL'
    if re.search(r'\b(laptop|computer|monitor|keyboard|printer|server|network|radio|camera|electronic|sensor|display)\b',x):return 'ELECTRONICS_SIGNAL'
    if re.search(r'\b(aircraft|missile|weapon|ammunition|engine|turbine|vehicle|truck|ship|submarine|radar system)\b',x):return 'HIGH_SPEC_DEFENSE_TRANSPORT'
    if re.search(r'\b(medical|surgical|implant|pharmaceutical|drug|laboratory reagent|diagnostic)\b',x):return 'REGULATED_MEDICAL_SIGNAL'
    if re.search(r'\b(machine|machinery|pump|compressor|generator|motor|industrial equipment|lathe|cnc)\b',x):return 'CAPITAL_EQUIPMENT_SIGNAL'
    return 'UNRESOLVED_PRODUCT_SHAPE'

def route(sub,sh):
    if sh in {'STANDARDIZED_MRO_CONSUMABLE_SIGNAL','PRINT_PACKAGING_SIGNAL','TEXTILE_APPAREL_SIGNAL'}:return 'BROKER_RESELL_HIGH_INTEREST'
    if sh in {'FURNITURE_SIGNAL','ELECTRONICS_SIGNAL'}:return 'BROKER_RESELL_CONDITIONAL'
    if sh in {'HIGH_SPEC_DEFENSE_TRANSPORT','REGULATED_MEDICAL_SIGNAL'}:return 'HARD_OR_REGULATED'
    if sh=='CAPITAL_EQUIPMENT_SIGNAL':return 'TECHNICAL_DISTRIBUTION_CONDITIONAL'
    if sub in {'APPAREL','TEXTILE_PRODUCTS','PAPER_PRODUCTS','PRINTING_RELATED','FURNITURE'}:return 'BROKER_RESELL_CONDITIONAL'
    if sub in {'TRANSPORT_EQUIPMENT','CHEMICALS','PETROLEUM_COAL'}:return 'HARD_OR_REGULATED'
    return 'OPEN_REVIEW'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=[r for r in read(a.input) if r.get('archetype')=='USA_MANUFACTURING']
    enriched=[];agg=defaultdict(lambda:{'clusters':0,'records':0.0,'buyers':0.0,'repeat':0.0,'suppliers':0.0})
    for r in rows:
        code=re.sub(r'\D','',r.get('native_code') or '');sub=NAICS3.get(code[:3],'OTHER_MANUFACTURING');sh=shape(r.get('example_titles'));rt=route(sub,sh);e=dict(r);e.update({'naics3':code[:3],'manufacturing_subsector':sub,'product_shape':sh,'manufacturing_routing':rt});enriched.append(e);g=agg[(sub,sh,rt)];g['clusters']+=1
        for fld,key in [('records','records'),('buyers','buyers'),('repeat_buyers','repeat'),('suppliers','suppliers')]:g[key]+=num(r.get(fld))
    with (out/'decomposed_clusters.csv').open('w',encoding='utf-8',newline='') as f:
        fields=list(enriched[0].keys()) if enriched else ['manufacturing_subsector'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(enriched)
    summary={'version':'HISTORICAL_OPEN_WORLD_USA_MANUFACTURING_DECOMP_V1','manufacturing_clusters':len(rows),'subsector_counts':{},'shape_counts':{},'routing_counts':{},'historical_only':True,'record_deletion':False,'warning':'USAspending NAICS is an award/supplier industry classification, not a guaranteed product taxonomy. Title examples are used only as a routing signal.'}
    for r in enriched:
        for k,fld in [('subsector_counts','manufacturing_subsector'),('shape_counts','product_shape'),('routing_counts','manufacturing_routing')]:summary[k][r[fld]]=summary[k].get(r[fld],0)+1
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# USA Manufacturing Residual Decomposition v1','',f'- USA manufacturing residual clusters **{len(rows):,}**','', 'NAICS describes industry, not necessarily an exact purchased SKU. This is an economic discovery layer; examples must be QA’d before promotion.','']
    for rt in ['BROKER_RESELL_HIGH_INTEREST','BROKER_RESELL_CONDITIONAL','TECHNICAL_DISTRIBUTION_CONDITIONAL','OPEN_REVIEW','HARD_OR_REGULATED']:
        subset=[r for r in enriched if r['manufacturing_routing']==rt];lines += [f'## {rt}',f'- clusters **{len(subset)}**','']
        subset=sorted(subset,key=lambda r:num(r.get('economic_score')),reverse=True)
        for r in subset[:40]:lines.append(f"- score {r.get('economic_score')} · {r['manufacturing_subsector']} · {r['product_shape']} · NAICS {r.get('native_code')} · records={r.get('records')} buyers={r.get('buyers')} suppliers={r.get('suppliers')} share={r.get('top_supplier_share')} median={r.get('median_value')} :: {r.get('example_titles')}")
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
