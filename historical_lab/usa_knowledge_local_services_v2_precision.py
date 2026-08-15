#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import duckdb

def write(path,header,rows):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8',newline='') as f:w=csv.writer(f);w.writerow(header);w.writerows(rows)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 con=duckdb.connect();con.execute('SET threads=4');con.execute("SET memory_limit='5GB'")
 h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=250000,compression='auto')";aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=250000,compression='auto')"
 con.execute(f"""
 CREATE TABLE x AS WITH hh AS (
  SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,
   coalesce(nullif(NAICS_Code,''),nullif(PSC_Code,''),nullif(CPV_NAICS_or_Local_Code,''),'UNKNOWN') native_code,
   coalesce(nullif(Subcategory,''),nullif(Raw_Spend_Category,''),nullif(Category,''),'UNKNOWN') native_subcategory,
   lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Subcategory,''),coalesce(Raw_Spend_Category,''),coalesce(Raw_CPV_Description,''))) txt
  FROM {h}), aa AS (
  SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,upper(coalesce(nullif(Currency,''),'USD')) currency FROM {aw})
 SELECT hh.*,aa.supplier,aa.award_value,aa.currency,
  CASE WHEN coalesce(aa.supplier,'')='' THEN 'UNKNOWN' WHEN regexp_matches(coalesce(aa.supplier,''),'(?i)(LLC|INC\.?|CORP|COMPANY|CO\.?|GROUP|ASSOCIATES|SERVICES|SOLUTIONS|PARTNERS|CONSULTING|AGENCY|AGENCIES|ENTERPRISES|LTD|LIMITED|PLLC|LP\b|UNIVERSITY|INSTITUTE|CENTER|CENTRE)') THEN 'ORG_LIKE' ELSE 'AMBIGUOUS_OR_INDIVIDUAL_LIKE' END supplier_shape
 FROM hh LEFT JOIN aa USING(tender_id)
 """)
 # Strict family rules. Native code 561492 is the US NAICS for court reporting/stenotype services and is high precision.
 con.execute("""
 CREATE TABLE c0 AS SELECT *,CASE
  WHEN regexp_matches(txt,'(?i)\bexpert witness(es)?\b') THEN 'EXPERT_WITNESS'
  WHEN regexp_matches(txt,'(?i)\b(litigative consultant|litigation consultant)\b') THEN 'LITIGATION_CONSULTANT'
  WHEN (native_code='561492' OR regexp_matches(txt,'(?i)\b(court reporting services?|court reporter services?|deposition reporting services?|stenotype services?)\b'))
       AND NOT regexp_matches(txt,'(?i)(notebook|stenographer.?s notebook|painting project|renovation project|office renovation|construction|furniture|paper supply)') THEN 'COURT_REPORTING_PRECISION'
  WHEN regexp_matches(txt,'(?i)\b(interpreter services?|interpreting services?|simultaneous interpretation|consecutive interpretation|language interpretation|oral interpretation|sign language interpreter|telephone interpretation|phone interpretation|video remote interpretation)\b')
       AND NOT regexp_matches(txt,'(?i)(radiograph|radiology|x-ray|xray|medical imaging|image interpretation|imagery interpretation|geological interpretation|geophysical interpretation|data interpretation|intelligence interpretation)') THEN 'LANGUAGE_INTERPRETATION_PRECISION'
  WHEN regexp_matches(txt,'(?i)\b(janitorial services?|janitorial service)\b') THEN 'JANITORIAL'
  WHEN regexp_matches(txt,'(?i)\b(custodial services?|custodial service)\b') THEN 'CUSTODIAL'
  WHEN regexp_matches(txt,'(?i)\b(pest control services?|pest management services?)\b') THEN 'PEST_CONTROL'
  WHEN regexp_matches(txt,'(?i)\b(laundry services?|laundry and dry cleaning services?|linen services?)\b') THEN 'LAUNDRY_LINEN'
  WHEN regexp_matches(txt,'(?i)\b(grounds maintenance services?|grounds maintenance|landscape maintenance services?|landscaping services?)\b') THEN 'GROUNDS_LANDSCAPING'
  WHEN regexp_matches(txt,'(?i)\b(lodging services?|hotel rooms?|hotel accommodation|temporary lodging|temporary accommodation)\b') THEN 'LODGING_HOTEL'
  ELSE NULL END service_family FROM x
 """)
 con.execute("CREATE TABLE y AS SELECT * FROM c0 WHERE service_family IS NOT NULL")
 # Interpretation delivery subtypes and expert supplier shape are retained for asymmetry analysis.
 con.execute("""
 CREATE TABLE z AS SELECT *,CASE
  WHEN service_family='LANGUAGE_INTERPRETATION_PRECISION' AND regexp_matches(txt,'(?i)(telephone|phone|telephonic|video remote|remote interpreting|virtual interpretation)') THEN 'REMOTE_PHONE_VIDEO'
  WHEN service_family='LANGUAGE_INTERPRETATION_PRECISION' AND regexp_matches(txt,'(?i)(simultaneous|conference interpretation)') THEN 'SIMULTANEOUS_CONFERENCE'
  WHEN service_family='LANGUAGE_INTERPRETATION_PRECISION' AND regexp_matches(txt,'(?i)(sign language|deaf|hard of hearing)') THEN 'SIGN_LANGUAGE_ACCESSIBILITY'
  WHEN service_family='LANGUAGE_INTERPRETATION_PRECISION' THEN 'GENERAL_LANGUAGE_INTERPRETATION'
  WHEN service_family='COURT_REPORTING_PRECISION' THEN 'COURT_REPORTING'
  WHEN service_family IN ('EXPERT_WITNESS','LITIGATION_CONSULTANT') THEN supplier_shape
  ELSE 'GENERAL' END service_subtype FROM y
 """)
 matrix=con.execute("""
 WITH b AS (SELECT service_family,service_subtype,native_code,native_subcategory,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier,'')) suppliers,
   quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_value,median(award_value) FILTER(WHERE award_value>=0) median_value,quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_value FROM z GROUP BY 1,2,3,4,5),
 rb0 AS (SELECT service_family,service_subtype,native_code,native_subcategory,currency,buyer,count(*) n FROM z WHERE buyer<>'' GROUP BY 1,2,3,4,5,6),
 rb AS (SELECT service_family,service_subtype,native_code,native_subcategory,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM rb0 GROUP BY 1,2,3,4,5),
 ss0 AS (SELECT service_family,service_subtype,native_code,native_subcategory,currency,supplier,count(*) n FROM z WHERE supplier<>'' GROUP BY 1,2,3,4,5,6),
 ss AS (SELECT service_family,service_subtype,native_code,native_subcategory,currency,max(n)*1.0/sum(n) top_supplier_share FROM ss0 GROUP BY 1,2,3,4,5)
 SELECT b.*,coalesce(rb.repeat_buyers,0),ss.top_supplier_share FROM b LEFT JOIN rb USING(service_family,service_subtype,native_code,native_subcategory,currency) LEFT JOIN ss USING(service_family,service_subtype,native_code,native_subcategory,currency)
 ORDER BY service_family,records DESC
 """).fetchall();write(out/'market_matrix.csv',['family','subtype','native_code','native_subcategory','currency','records','buyers','suppliers','p25_value','median_value','p75_value','repeat_buyers','top_supplier_share'],matrix)
 broad=con.execute("""
 WITH b AS (SELECT service_family,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier,'')) suppliers,median(award_value) FILTER(WHERE award_value>=0) median_value FROM z GROUP BY 1),
 ss0 AS (SELECT service_family,supplier,count(*) n FROM z WHERE supplier<>'' GROUP BY 1,2),ss AS (SELECT service_family,max(n)*1.0/sum(n) top_supplier_share FROM ss0 GROUP BY 1)
 SELECT b.*,ss.top_supplier_share FROM b LEFT JOIN ss USING(service_family) ORDER BY records DESC
 """).fetchall();write(out/'family_summary.csv',['service_family','records','buyers','suppliers','median_value','top_supplier_share'],broad)
 expert_shape=con.execute("""SELECT service_family,supplier_shape,count(*) awards,count(distinct nullif(supplier,'')) suppliers,median(award_value) FILTER(WHERE award_value>=0) median_value FROM z WHERE service_family IN ('EXPERT_WITNESS','LITIGATION_CONSULTANT') GROUP BY 1,2 ORDER BY 1,3 DESC""").fetchall();write(out/'expert_supplier_shape.csv',['service_family','supplier_shape','awards','suppliers','median_value'],expert_shape)
 winners=con.execute("""SELECT service_family,service_subtype,native_code,currency,supplier,count(*) awards,count(*)*1.0/sum(count(*)) over(partition by service_family,service_subtype,native_code,currency) supplier_share,supplier_shape FROM z WHERE supplier<>'' GROUP BY 1,2,3,4,5,7 QUALIFY row_number() over(partition by service_family,service_subtype,native_code,currency order by count(*) desc,supplier)<=20 ORDER BY service_family,service_subtype,awards DESC""").fetchall();write(out/'top_winners.csv',['family','subtype','native_code','currency','supplier','awards','supplier_share','supplier_shape'],winners)
 buyers=con.execute("""SELECT service_family,service_subtype,native_code,currency,buyer,count(*) awards FROM z WHERE buyer<>'' GROUP BY 1,2,3,4,5 QUALIFY row_number() over(partition by service_family,service_subtype,native_code,currency order by count(*) desc,buyer)<=20 ORDER BY service_family,service_subtype,awards DESC""").fetchall();write(out/'top_buyers.csv',['family','subtype','native_code','currency','buyer','awards'],buyers)
 examples=con.execute("""SELECT service_family,service_subtype,native_code,native_subcategory,currency,tender_id,buyer,supplier,title,award_value FROM z QUALIFY row_number() over(partition by service_family,service_subtype,native_code,currency order by award_value desc nulls last,tender_id)<=15 ORDER BY service_family,service_subtype,native_code,award_value DESC NULLS LAST""").fetchall();write(out/'examples.csv',['family','subtype','native_code','native_subcategory','currency','tender_id','buyer','supplier','title','award_value'],examples)
 summary={'version':'HISTORICAL_US_KNOWLEDGE_LOCAL_SERVICES_V2_PRECISION','archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'precision_rows':con.execute('select count(*) from z').fetchone()[0],'families':dict(con.execute('select service_family,count(*) from z group by 1 order by 2 desc').fetchall()),'grain':'AWARD_FIRST_PROCUREMENT','historical_only':True,'v1_supersession':'Court-reporting and interpretation v1 broad counts are superseded by precision rules here; underlying records preserved.','live_used':False,'dce_used':False}
 (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
 lines=['# USA Knowledge + Local Services Precision v2','',f"- USAspending records scanned **{summary['archive_records_scanned']:,}** · precision classified **{summary['precision_rows']:,}**",'', 'v2 specifically fixes false court-reporting and non-language interpretation matches. All excluded records remain in the historical archive for other classifications.','']
 for fam,n,buy,sup,med,share in broad:lines += [f'## {fam}',f'- records **{n}** · buyers **{buy}** · suppliers **{sup}** · median award **{med if med is not None else "UNKNOWN"} USD** · top share **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
 lines += ['## Expert supplier-name shape (heuristic)']
 for r in expert_shape:lines.append(f'- {r[0]} / {r[1]}: awards **{r[2]}**, suppliers **{r[3]}**, median **{r[4]}**')
 (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
