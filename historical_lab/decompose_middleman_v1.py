#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json,re
from datetime import datetime,timezone
from pathlib import Path

import duckdb

from pipeline.exhaustive_record_reader_v1 import choose,cols_for,double_expr,lit,relation,text_expr


def write_csv(path, header, rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(header); w.writerows(rows)


def sql_lit(s:str)->str:
    return "'"+s.replace("'","''")+"'"


def classifier(expr:str, mapping:list[tuple[str,str]], default:str)->str:
    parts=['CASE']
    for label,pat in mapping:
        parts.append(f"WHEN regexp_matches({expr},{sql_lit(pat)}) THEN {sql_lit(label)}")
    parts.append(f"ELSE {sql_lit(default)} END")
    return ' '.join(parts)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--bridge',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(out/'work.duckdb'));con.execute("SET memory_limit='5GB'");con.execute('SET threads=4');con.execute('SET preserve_insertion_order=false')
    hrel=relation(Path(a.historical));arel=relation(Path(a.awards));brel=relation(Path(a.bridge))
    hc,ac,bc=cols_for(con,hrel),cols_for(con,arel),cols_for(con,brel)
    hid=choose(hc,'Tender_ID','Procurement_ID','Contract_ID','tender_id','id')
    title=choose(hc,'Title','Contract_Title','Description','title');scope=choose(hc,'Scope_Summary','Description','Scope','description')
    coded=choose(hc,'CPV_Description','NAICS_Description','PSC_Description','Category','Subcategory','code_description')
    country=choose(hc,'Country','country');cur=choose(hc,'Currency','currency');buyer=choose(hc,'Buyer_Name','Contracting_Authority','Awarding_Agency','Agency_Name','buyer_name')
    hest=choose(hc,'Estimated_Value','Contract_Value','Award_Value','Total_Obligation','value');hbid=choose(hc,'Bidder_Count','Tenderer_Count','Number_Of_Bids','bidder_count')
    hproc=choose(hc,'Procurement_Procedure','Procedure','Procedure_Type','procurement_procedure')
    aid=choose(ac,'Award_ID','Contract_ID','award_id','id');atid=choose(ac,'Tender_ID','Procurement_ID','tender_id');aval=choose(ac,'Award_Value','Contract_Value','Total_Obligation','value')
    baid=choose(bc,'Award_ID','Contract_ID','award_id');bsid=choose(bc,'Supplier_ID','Recipient_ID','supplier_id');bsname=choose(bc,'Supplier_Name','Recipient_Name','supplier_name')
    if not hid: raise SystemExit('missing historical procurement id')

    tid=text_expr(hid);t=text_expr(title);s=text_expr(scope);cd=text_expr(coded);cty=text_expr(country,"'UNKNOWN'");currency=f"upper(coalesce(nullif({text_expr(cur)},''),'UNKNOWN'))" if cur else "'UNKNOWN'"
    b=text_expr(buyer);est=double_expr(hest);bid=double_expr(hbid);proc=text_expr(hproc,"'UNKNOWN'")
    txt=f"lower(concat_ws(' ',{t},{s},{cd}))"

    families=[
      ('SOFTWARE_BROKER',r'(?i)(softwarebroker|software[ -]broker|licentiemakelaar|licentie[ -]broker|software.*reseller|reseller.*software|lizenzbroker|jälleenmyynti|återförsälj.*(programvara|licens)|licens.*återförsälj|revenda.*software|revendedor.*software|software.*resale|licen[cs].*reseller|value added re[- ]seller|licensing solution partner)'),
      ('CONSULTANT_BROKER',r'(?i)(konsultmäklare|konsultförmedl|consultant broker|consultancy broker|consultant brokerage|consultant marketplace|courtier.*consultant|intermédiation.*consultant|intermediation.*consultant)'),
      ('STAFFING_INTERMEDIARY',r'(?i)(labou?r hire|temporary personnel|temporary help services|temporary staffing|staffing services|personaldienstleist|personalvermittlung|intérim|interim staffing|agence.*intérim|uitzend|detacher|mise à disposition de personnel|mise a disposition de personnel|personnels? temporaires)'),
      ('POSTAL_FULFILMENT',r'(?i)(postzustellungsauftrag|zustellung von bescheiden|official notice delivery|postal fulfil|postal fulfillment|mise sous pli|routage postal|courrier.*distribution|affranchissement|bulk mail|mailing services|postal services)'),
      ('CLEANING_CONSUMABLES',r'(?i)(puhtaanapidon tarvikkeet|cleaning supplies|cleaning consumables|janitorial supplies|produits d.?entretien|fournitures.*nettoyage|reinigungsmittel.*liefer|reinigungs.*verbrauchsmaterial|hygiene supplies|produits.*hygiène|produits.*hygiene)'),
    ]
    family_case=classifier('txt',families,'NO_MATCH')

    # Context-sensitive subfamilies. Heavy/regulatory variants remain visible rather than being silently dropped.
    sw_vendor=[('MICROSOFT',r'(?i)(microsoft|azure|m365|office 365|office365)'),('ADOBE',r'(?i)adobe'),('RED_HAT',r'(?i)red[ -]?hat|openshift'),('VMWARE_BROADCOM',r'(?i)(vmware|broadcom)'),('VEEAM',r'(?i)veeam'),('ORACLE',r'(?i)oracle'),('IBM_HCL',r'(?i)(\bibm\b|\bhcl\b)'),('SAP',r'(?i)\bsap\b'),('ATLASSIAN',r'(?i)atlassian|jira|confluence'),('GOOGLE_CLOUD',r'(?i)(google cloud|gcp)'),('AWS',r'(?i)(amazon web services|\baws\b)'),('CITRIX',r'(?i)citrix'),('NUTANIX',r'(?i)nutanix'),('SECURITY_SOFTWARE',r'(?i)(darktrace|security software|cybersecurity|antivirus|endpoint protection)'),('VIRTUALIZATION',r'(?i)(virtuali[sz]ation|hypervisor)'),]
    staff=[('HEALTH_CLINICAL',r'(?i)(nurs|nurse|nursing|médical|medical|médecin|doctor|physician|care staff|health)'),('IT_DIGITAL',r'(?i)(\bit\b|ict|computer|application support|developer|software|data|cyber|technical writer|business analyst)'),('PROJECT_PROGRAM',r'(?i)(project manager|program manager|programme manager|project support|pm[o ]|project officer)'),('EDUCATION',r'(?i)(teacher|teaching|education|school)'),('LEGAL',r'(?i)(legal|lawyer|solicitor|jurist)'),('CLEANING_FACILITY',r'(?i)(cleaning|entretien ménager|entretien menager|facility|facilities|horeca|catering)'),('ADMIN_OFFICE',r'(?i)(administrative|office|clerical|secretar|advisor|adviser|support staff)'),]
    consult=[('IT_CONSULTANTS',r'(?i)(\bit\b|ict|software|digital|cyber|data)'),('ENGINEERING_PROJECT',r'(?i)(engineer|engineering|projektingenjör|teknikingenjör)'),('LEADERSHIP_MANAGEMENT',r'(?i)(management|leadership|chef|ledarskap)'),]
    postal=[('PRINT_INSERT_POST',r'(?i)(impression|printing|print|mise sous pli|folding|envelope|édition|edition)'),('POSTAL_DELIVERY',r'(?i)(postzustell|postal|postdienst|affranchissement|postage|mailing|courrier)'),('COURIER_EXPRESS',r'(?i)(courier|express|colis|parcel)'),('MAIL_EQUIPMENT',r'(?i)(machine.*mise sous pli|inserter|franking machine|affranchissement.*machine)'),]
    cleaning=[('PAPER_HYGIENE',r'(?i)(toilet paper|paper towel|ouate|papier.*hygiène|papier.*hygiene|tissue)'),('DETERGENTS_CHEMICALS',r'(?i)(detergent|chemical|produits? d.?entretien|reinigungsmittel|lessiviel|soap|savon)'),('BAGS_WASTE',r'(?i)(waste bag|refuse sack|garbage bag|sac.*déchet|sac.*dechet|müllbeutel)'),('TOOLS_SMALL_EQUIPMENT',r'(?i)(small equipment|petit matériel|petit materiel|cleaning equipment|brosserie|mop|brush|accessor)'),('KITCHEN_HYGIENE',r'(?i)(kitchen|cuisine|food service|vaisselle)'),('PPE_WORKWEAR',r'(?i)(ppe|workwear|protective clothing|glove|gant)'),]
    software_case=classifier('txt',sw_vendor,'GENERIC_OR_MULTI_VENDOR')
    staff_case=classifier('txt',staff,'GENERIC_TEMP_STAFFING')
    consult_case=classifier('txt',consult,'GENERIC_CONSULTANT_BROKER')
    postal_case=classifier('txt',postal,'GENERIC_POSTAL_FULFILMENT')
    clean_case=classifier('txt',cleaning,'GENERIC_CLEANING_CONSUMABLES')
    sub_case=f"CASE WHEN intermediary_family='SOFTWARE_BROKER' THEN {software_case} WHEN intermediary_family='STAFFING_INTERMEDIARY' THEN {staff_case} WHEN intermediary_family='CONSULTANT_BROKER' THEN {consult_case} WHEN intermediary_family='POSTAL_FULFILMENT' THEN {postal_case} WHEN intermediary_family='CLEANING_CONSUMABLES' THEN {clean_case} ELSE 'OTHER' END"

    # Tender-level award values and supplier links.
    if atid:
        at=text_expr(atid);av=double_expr(aval)
        con.execute(f"CREATE TABLE award_stats AS SELECT {at} tender_id, median({av}) FILTER(WHERE {av}>=0) median_award_value FROM {arel} GROUP BY 1")
    else: con.execute("CREATE TABLE award_stats(tender_id varchar,median_award_value double)")
    if aid and atid and baid:
        ak=text_expr(aid);at=text_expr(atid);bk=text_expr(baid);sid=text_expr(bsid) if bsid else "''";sn=text_expr(bsname) if bsname else "''"
        con.execute(f"""
        CREATE TABLE tender_suppliers AS
        WITH aw AS (SELECT {ak} award_id,{at} tender_id FROM {arel}),
        br0 AS (SELECT {bk} award_id,coalesce(nullif({sid},''),nullif({sn},''),'UNKNOWN_SUPPLIER') supplier_id,coalesce(nullif({sn},''),nullif({sid},''),'UNKNOWN_SUPPLIER') supplier_name FROM {brel}),
        br AS (SELECT *,count(*) over(partition by award_id) n FROM br0)
        SELECT aw.tender_id,br.supplier_id,br.supplier_name,1.0/nullif(br.n,0) supplier_weight FROM aw JOIN br USING(award_id)
        """)
    else: con.execute("CREATE TABLE tender_suppliers(tender_id varchar,supplier_id varchar,supplier_name varchar,supplier_weight double)")

    con.execute(f"""
    CREATE TABLE proc0 AS
    SELECT {tid} tender_id,{cty} country,{currency} currency,{b} buyer_name,{t} title,{proc} procedure,{est} estimated_value,{bid} bidder_count,{txt} txt,{family_case} intermediary_family
    FROM {hrel}
    """)
    con.execute(f"""
    CREATE TABLE proc AS
    SELECT p.*, {sub_case} subfamily,coalesce(a.median_award_value,p.estimated_value) reference_value
    FROM proc0 p LEFT JOIN award_stats a USING(tender_id)
    WHERE intermediary_family<>'NO_MATCH'
    """)

    # Buyer recurrence.
    con.execute("CREATE TABLE buyer_stats0 AS SELECT intermediary_family,subfamily,country,currency,buyer_name,count(*) n FROM proc WHERE buyer_name<>'' GROUP BY 1,2,3,4,5")
    con.execute("CREATE TABLE buyer_stats AS SELECT intermediary_family,subfamily,country,currency,count(*) FILTER(WHERE n>=2) repeat_buyers,max(n) top_buyer_records FROM buyer_stats0 GROUP BY 1,2,3,4")
    # Supplier concentration is fractionalized and based only on linked awards.
    con.execute("""
    CREATE TABLE supplier_sub AS
    SELECT p.intermediary_family,p.subfamily,p.country,p.currency,ts.supplier_id,any_value(ts.supplier_name) supplier_name,sum(ts.supplier_weight) weighted_awards
    FROM proc p JOIN tender_suppliers ts USING(tender_id) WHERE ts.supplier_id<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4,5
    """)
    con.execute("""
    CREATE TABLE supplier_stats AS
    SELECT intermediary_family,subfamily,country,currency,count(*) suppliers,sum(weighted_awards) linked_award_weight,max(weighted_awards) top_supplier_weight,
           CASE WHEN sum(weighted_awards)>0 THEN max(weighted_awards)/sum(weighted_awards) END top_supplier_share
    FROM supplier_sub GROUP BY 1,2,3,4
    """)
    matrix=con.execute("""
    WITH base AS (
      SELECT intermediary_family,subfamily,country,currency,count(*) records,count(distinct nullif(buyer_name,'')) buyers,
             quantile_cont(reference_value,.25) FILTER(WHERE reference_value>=0) p25_value,
             median(reference_value) FILTER(WHERE reference_value>=0) median_value,
             quantile_cont(reference_value,.75) FILTER(WHERE reference_value>=0) p75_value,
             median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders
      FROM proc GROUP BY 1,2,3,4)
    SELECT b.*,coalesce(x.repeat_buyers,0) repeat_buyers,s.suppliers,s.linked_award_weight,s.top_supplier_share
    FROM base b LEFT JOIN buyer_stats x USING(intermediary_family,subfamily,country,currency)
    LEFT JOIN supplier_stats s USING(intermediary_family,subfamily,country,currency)
    ORDER BY b.records DESC,b.country,b.currency,b.subfamily
    """).fetchall()
    mh=['family','subfamily','country','currency','records','buyers','p25_value','median_value','p75_value','median_bidders','repeat_buyers','suppliers','linked_award_weight','top_supplier_share']
    write_csv(out/'submarket_matrix.csv',mh,matrix)

    winners=con.execute("""
    SELECT intermediary_family,subfamily,country,currency,supplier_name,weighted_awards,
           weighted_awards/nullif(sum(weighted_awards) over(partition by intermediary_family,subfamily,country,currency),0) supplier_share
    FROM supplier_sub QUALIFY row_number() over(partition by intermediary_family,subfamily,country,currency order by weighted_awards desc,supplier_name)<=10
    ORDER BY intermediary_family,subfamily,country,currency,weighted_awards DESC
    """).fetchall()
    write_csv(out/'top_winners.csv',['family','subfamily','country','currency','supplier_name','weighted_awards','supplier_share'],winners)
    buyers=con.execute("""
    SELECT intermediary_family,subfamily,country,currency,buyer_name,n FROM buyer_stats0
    QUALIFY row_number() over(partition by intermediary_family,subfamily,country,currency order by n desc,buyer_name)<=10
    ORDER BY intermediary_family,subfamily,country,currency,n DESC
    """).fetchall()
    write_csv(out/'top_buyers.csv',['family','subfamily','country','currency','buyer_name','records'],buyers)
    examples=con.execute("""
    SELECT intermediary_family,subfamily,country,currency,tender_id,buyer_name,title,reference_value,bidder_count,procedure
    FROM proc
    QUALIFY row_number() over(partition by intermediary_family,subfamily,country,currency order by reference_value desc nulls last,tender_id)<=5
    ORDER BY intermediary_family,subfamily,country,currency,reference_value DESC NULLS LAST
    """).fetchall()
    write_csv(out/'examples.csv',['family','subfamily','country','currency','tender_id','buyer_name','title','reference_value','bidder_count','procedure'],examples)

    summary={'version':'SPM_HISTORICAL_MIDDLEMAN_DECOMPOSITION_V1','generated_at':datetime.now(timezone.utc).isoformat(),'historical_records_scanned':con.execute(f'SELECT count(*) FROM {hrel}').fetchone()[0],'matched_records':con.execute('SELECT count(*) FROM proc').fetchone()[0],'submarkets':len(matrix),'families':dict(con.execute('SELECT intermediary_family,count(*) FROM proc GROUP BY 1 ORDER BY 2 DESC').fetchall()),'historical_only':True,'live_used':False,'dce_used':False,'supplier_weights':'fractionalized per award','currency_mixing':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    # Compact report with highest-volume submarkets.
    lines=['# Historical Middleman Decomposition v1','',f"- Raw Global Core records scanned: **{summary['historical_records_scanned']:,}**",f"- Strict middleman-family matches: **{summary['matched_records']:,}**",f"- Country/currency/subfamily markets: **{summary['submarkets']:,}**",'', 'Historical-only. Supplier concentration is fractionalized over linked award-supplier evidence. Missing supplier/bidder/value evidence stays UNKNOWN.','']
    for r in matrix[:160]:
        fam,sub,country,currency,records,buyers,p25,med,p75,mb,rb,sup,linked,share=r
        lines += [f'## {fam} — {sub} — {country} / {currency}',f'- records **{records}** · buyers **{buyers}** · repeat buyers **{rb}** · median **{med if med is not None else "UNKNOWN"}** · p25/p75 **{p25 if p25 is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}**',f'- median bidders **{mb if mb is not None else "UNKNOWN"}** · linked suppliers **{sup if sup is not None else "UNKNOWN"}** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    con.close()

if __name__=='__main__':main()
