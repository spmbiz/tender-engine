#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,csv,re,math
from collections import defaultdict
from pathlib import Path

CPV2={
 '03':'AGRI_FOOD_RAW','09':'ENERGY_FUEL_ELECTRICITY','14':'MINING_RAW_MATERIALS','15':'FOOD_BEVERAGE','18':'APPAREL_WORKWEAR','19':'TEXTILE_PLASTIC_RUBBER','22':'PRINTED_MATTER','24':'CHEMICALS','30':'OFFICE_IT_EQUIPMENT','31':'ELECTRICAL_EQUIPMENT','32':'TELECOM_ELECTRONICS','33':'MEDICAL_PHARMA','34':'VEHICLES_TRANSPORT_EQUIPMENT','35':'SECURITY_FIRE_EQUIPMENT','37':'SPORT_RECREATION_MUSICAL','38':'LAB_PRECISION_INSTRUMENTS','39':'FURNITURE_MISC_MANUFACTURED','41':'PUMPS_WATER_EQUIPMENT','42':'INDUSTRIAL_MACHINERY','43':'MINING_CONSTRUCTION_MACHINERY','44':'CONSTRUCTION_MATERIALS','45':'CONSTRUCTION_WORKS','48':'SOFTWARE','50':'REPAIR_MAINTENANCE','51':'INSTALLATION_SERVICES','55':'HOTEL_RESTAURANT','60':'TRANSPORT_SERVICES','63':'TRAVEL_TRANSPORT_SUPPORT','64':'POSTAL_TELECOM','65':'PUBLIC_UTILITIES','66':'FINANCIAL_INSURANCE','70':'REAL_ESTATE','71':'ENGINEERING_ARCHITECTURE','72':'IT_SERVICES','73':'RND_SERVICES','75':'PUBLIC_ADMIN_SERVICES','76':'OIL_GAS_SERVICES','77':'AGRI_FORESTRY_SERVICES','79':'BUSINESS_SERVICES','80':'EDUCATION_TRAINING','85':'HEALTH_SOCIAL','90':'ENVIRONMENT_WASTE_CLEANING','92':'CULTURE_RECREATION','98':'OTHER_COMMUNITY_PERSONAL'}

NAICS2={
 '11':'AGRI_FORESTRY','21':'MINING_OIL_GAS','22':'UTILITIES','23':'CONSTRUCTION','31':'MANUFACTURING','32':'MANUFACTURING','33':'MANUFACTURING','42':'WHOLESALE_DISTRIBUTION','44':'RETAIL','45':'RETAIL','48':'TRANSPORT_WAREHOUSE','49':'TRANSPORT_WAREHOUSE','51':'INFORMATION','52':'FINANCE_INSURANCE','53':'REAL_ESTATE_RENTAL','54':'PROFESSIONAL_SERVICES','55':'MANAGEMENT','56':'ADMIN_SUPPORT_WASTE','61':'EDUCATION','62':'HEALTH_SOCIAL','71':'ARTS_RECREATION','72':'ACCOMMODATION_FOOD','81':'OTHER_SERVICES','92':'PUBLIC_ADMIN'}

def load(path):
    rows=[]
    with open(path,encoding='utf-8') as f:
        for line in f:
            if line.strip():rows.append(json.loads(line))
    return rows

def fnum(x):
    try:return float(x)
    except:return 0.0

def text(r):
    ex=' '.join((e.get('title') or '') for e in (r.get('examples') or []))
    return ' '.join([str(r.get('code_description') or ''),str(r.get('phrase_signature') or ''),ex]).lower()

def archetype(r):
    src=(r.get('source') or '').lower(); k=r.get('cluster_key') or {}; code=str(k.get('native_code') or '')
    t=text(r)
    # High precision semantic overrides first.
    if re.search(r'\b(toner|ink cartridge|printer cartridge|cartouche|tonerkart)',t):return 'TONER_PRINTER_CONSUMABLES'
    if re.search(r'\b(furniture|mobilier|möbel|meubles|office chair|desk|furnishing)',t):return 'FURNITURE_SUPPLY_INSTALL'
    if re.search(r'\b(cleaning service|janitorial|building cleaning|nettoyage|reinigung|почистване)',t):return 'CLEANING_LOCAL_SERVICE'
    if re.search(r'\b(laboratory reagent|reagent|reactive|reactif|реактив)',t):return 'LAB_REAGENTS_CONSUMABLES'
    if re.search(r'\b(office supplies|stationery|papeterie|kantoorbenodigdheden|büromaterial)',t):return 'OFFICE_STATIONERY'
    if re.search(r'\b(workwear|uniform|protective clothing|safety footwear|werkkleding|arbeitskleidung)',t):return 'WORKWEAR_UNIFORMS'
    if re.search(r'\b(promotional|goodies|merchandise|objets publicitaires|werbeartikel)',t):return 'PROMOTIONAL_MERCH'
    if re.search(r'\b(signage|signs|signalétique|beschilderung)',t):return 'SIGNAGE'
    if re.search(r'\b(catering|food products|food supplies|groceries|alimentation|хранителни)',t):return 'FOOD_SUPPLY'
    if re.search(r'\b(electricity|electrical energy|electric energy|електрическа енергия)',t):return 'ELECTRICITY_SUPPLY_AGGREGATION'
    if re.search(r'\b(diesel|petrol|gasoline|fuel supply|гориво)',t):return 'FUEL_SUPPLY'
    if re.search(r'\b(pharmaceutical|medicinal product|drug supply|лекарствени)',t):return 'PHARMA_SUPPLY_REGULATED'
    if re.search(r'\b(medical device|medical consumable|implant|медицински изделия)',t):return 'MEDICAL_DEVICES_REGULATED'
    if re.search(r'\b(vehicle|cars|automobile|автомобил)',t):return 'VEHICLE_SUPPLY'
    if re.search(r'\b(passenger transport|bus service|public transport|превоз на пътници)',t):return 'PASSENGER_TRANSPORT_LOCAL'
    if re.search(r'\b(software licence|software license|saas|subscription software)',t):return 'SOFTWARE_RESELL'
    # Native-code families.
    if src=='global_core' and re.fullmatch(r'\d{8}',re.sub(r'\D','',code)[:8] or ''):
        c=re.sub(r'\D','',code)[:2];return CPV2.get(c,'GLOBAL_OTHER')
    if src=='global_core':
        digits=re.sub(r'\D','',code)
        if len(digits)>=2:return CPV2.get(digits[:2],'GLOBAL_OTHER')
    if src=='usa':
        digits=re.sub(r'\D','',code)
        if len(digits)>=2:return 'USA_'+NAICS2.get(digits[:2],'OTHER')
    if src=='australia':
        # AusTender category text is often more useful than opaque code.
        d=(r.get('code_description') or '').lower()
        if 'recruit' in d:return 'AU_RECRUITMENT'
        if 'training' in d:return 'AU_TRAINING'
        if 'legal' in d:return 'AU_LEGAL'
        if 'consult' in d or 'professional' in d:return 'AU_PROFESSIONAL_SERVICES'
        if 'hardware' in d or 'computer' in d:return 'AU_IT_HARDWARE'
        if 'travel' in d or 'accommodation' in d:return 'AU_TRAVEL_ACCOMMODATION'
        return 'AU_OTHER'
    return 'OTHER'

def model(r,a):
    # Routing heuristic, not a verdict.
    hard={'CONSTRUCTION_WORKS','PHARMA_SUPPLY_REGULATED','MEDICAL_DEVICES_REGULATED','PASSENGER_TRANSPORT_LOCAL','FUEL_SUPPLY','VEHICLE_SUPPLY','HEALTH_SOCIAL','USA_CONSTRUCTION','USA_HEALTH_SOCIAL'}
    core={'BUSINESS_SERVICES','IT_SERVICES','PROFESSIONAL_SERVICES','USA_PROFESSIONAL_SERVICES','INFORMATION','USA_INFORMATION'}
    broker={'TONER_PRINTER_CONSUMABLES','FURNITURE_SUPPLY_INSTALL','OFFICE_STATIONERY','WORKWEAR_UNIFORMS','PROMOTIONAL_MERCH','SIGNAGE','LAB_REAGENTS_CONSUMABLES','FOOD_SUPPLY','OFFICE_IT_EQUIPMENT','ELECTRICAL_EQUIPMENT','TELECOM_ELECTRONICS','SPORT_RECREATION_MUSICAL','FURNITURE_MISC_MANUFACTURED','SOFTWARE_RESELL','AU_IT_HARDWARE'}
    local={'CLEANING_LOCAL_SERVICE','REPAIR_MAINTENANCE','INSTALLATION_SERVICES','ENVIRONMENT_WASTE_CLEANING','USA_ADMIN_SUPPORT_WASTE'}
    if a in hard:return 'HARD_OR_REGULATED'
    if a=='ELECTRICITY_SUPPLY_AGGREGATION':return 'BROKER_HYPOTHESIS_COMPLEX_MARKET'
    if a in broker:return 'BROKER_RESELL_CANDIDATE'
    if a in local:return 'LOCAL_NETWORK_CANDIDATE'
    if a in core:return 'CORE_OR_PARTNER_SERVICE'
    return 'OPEN_REVIEW'

def triage_score(r,a,route):
    records=fnum(r.get('records'));buyers=fnum(r.get('buyers'));repeat=fnum(r.get('repeat_buyers'));sup=fnum(r.get('suppliers'));share=fnum(r.get('top_supplier_share'));bid=fnum(r.get('median_bidders'))
    s=math.log1p(records)*9+math.log1p(buyers)*6+math.log1p(repeat)*5+math.log1p(sup)*3
    if share>0:s+=max(0,1-share)*15
    if bid>0:s+=min(bid,5)*2
    if route=='BROKER_RESELL_CANDIDATE':s+=10
    elif route=='CORE_OR_PARTNER_SERVICE':s+=8
    elif route=='LOCAL_NETWORK_CANDIDATE':s+=3
    elif route=='HARD_OR_REGULATED':s-=15
    return round(s,3)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=load(a.input); classified=[];agg=defaultdict(lambda:{'clusters':0,'records':0.0,'buyers':0.0,'repeat':0.0,'suppliers':0.0,'examples':[]})
    for r in rows:
        ar=archetype(r);route=model(r,ar);score=triage_score(r,ar,route);classified.append((score,ar,route,r));g=agg[(ar,route)];g['clusters']+=1
        for fld,key in [('records','records'),('buyers','buyers'),('repeat_buyers','repeat'),('suppliers','suppliers')]:g[key]+=fnum(r.get(fld))
        if len(g['examples'])<8:g['examples'].append(r)
    classified.sort(key=lambda x:x[0],reverse=True)
    with (out/'classified_clusters.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['economic_score','archetype','routing','source','triage','records','buyers','repeat_buyers','suppliers','top_supplier_share','median_value','median_bidders','native_code','code_description','phrase_signature','example_titles'])
        for score,ar,route,r in classified:
            k=r.get('cluster_key') or {};titles=' || '.join((e.get('title') or '') for e in (r.get('examples') or [])[:4])
            w.writerow([score,ar,route,r.get('source'),r.get('triage'),r.get('records'),r.get('buyers'),r.get('repeat_buyers'),r.get('suppliers'),r.get('top_supplier_share'),r.get('median_value'),r.get('median_bidders'),k.get('native_code'),r.get('code_description'),r.get('phrase_signature'),titles])
    summary={'version':'HISTORICAL_OPEN_WORLD_ECONOMIC_ARCHETYPES_V4','clusters_classified':len(rows),'routing_counts':{},'archetype_counts':{},'historical_only':True,'record_deletion':False,'score_role':'MODEL_ROUTING_HEURISTIC_NOT_FACT'}
    for _,ar,route,_ in classified:summary['routing_counts'][route]=summary['routing_counts'].get(route,0)+1;summary['archetype_counts'][ar]=summary['archetype_counts'].get(ar,0)+1
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Open-World Economic Archetypes v4','',f'- previously untagged clusters classified **{len(rows):,}**','', 'This is a native-code/economic routing layer, not a procurement verdict. It exists to expose broker/reseller/local-network opportunities that service-keyword ontologies miss.','']
    for route in ['BROKER_RESELL_CANDIDATE','CORE_OR_PARTNER_SERVICE','LOCAL_NETWORK_CANDIDATE','BROKER_HYPOTHESIS_COMPLEX_MARKET','OPEN_REVIEW','HARD_OR_REGULATED']:
        subset=[x for x in classified if x[2]==route];lines += [f'## {route}',f'- clusters **{len(subset)}**','']
        for score,ar,_,r in subset[:25]:
            k=r.get('cluster_key') or {};titles=' | '.join((e.get('title') or '') for e in (r.get('examples') or [])[:3])
            lines.append(f"- score {score} · {ar} · {r.get('source')} · code={k.get('native_code')} · records={r.get('records')} buyers={r.get('buyers')} suppliers={r.get('suppliers')} share={r.get('top_supplier_share')} bidders={r.get('median_bidders')} :: {titles}")
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
