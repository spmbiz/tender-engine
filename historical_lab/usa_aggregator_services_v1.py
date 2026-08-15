#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import duckdb


def write(path,header,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute('SET threads=4');con.execute("SET memory_limit='5GB'")
    h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=250000,compression='auto')"
    aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=250000,compression='auto')"
    con.execute(f"""
      CREATE TABLE x AS
      WITH hh AS (
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,
               coalesce(nullif(NAICS_Code,''),nullif(PSC_Code,''),nullif(CPV_NAICS_or_Local_Code,''),'UNKNOWN') native_code,
               coalesce(nullif(Subcategory,''),nullif(Raw_Spend_Category,''),nullif(Category,''),'UNKNOWN') native_subcategory,
               lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Subcategory,''),coalesce(Raw_Spend_Category,''),coalesce(Raw_CPV_Description,''))) txt
        FROM {h}
      ), aa AS (
        SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,
               upper(coalesce(nullif(Currency,''),'USD')) currency
        FROM {aw}
      ) SELECT hh.*,aa.supplier,aa.award_value,aa.currency FROM hh LEFT JOIN aa USING(tender_id)
    """)
    con.execute("""
      CREATE TABLE y0 AS
      SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(expert witness)') THEN 'EXPERT_WITNESS'
        WHEN regexp_matches(txt,'(?i)(litigative consultant|litigation consultant)') THEN 'LITIGATION_CONSULTANT'
        WHEN regexp_matches(txt,'(?i)(court reporter|court reporting|deposition reporting|stenograph)') THEN 'COURT_REPORTING'
        WHEN regexp_matches(txt,'(?i)(interpreter services|interpretation services|language interpretation|oral interpretation)') THEN 'INTERPRETATION'
        WHEN regexp_matches(txt,'(?i)(janitorial services|janitorial service)') THEN 'JANITORIAL'
        WHEN regexp_matches(txt,'(?i)(custodial services|custodial service)') THEN 'CUSTODIAL'
        WHEN regexp_matches(txt,'(?i)(pest control services|pest management services)') THEN 'PEST_CONTROL'
        WHEN regexp_matches(txt,'(?i)(laundry services|laundry and dry cleaning|linen services)') THEN 'LAUNDRY_LINEN'
        WHEN regexp_matches(txt,'(?i)(grounds maintenance|landscape maintenance|landscaping services)') THEN 'GROUNDS_LANDSCAPING'
        WHEN regexp_matches(txt,'(?i)(lodging|hotel rooms|hotel services|hotel accommodation|temporary accommodation)') THEN 'LODGING_HOTEL'
        ELSE NULL END service_family
      FROM x
    """)
    con.execute("""
      CREATE TABLE y AS SELECT *,CASE
        WHEN service_family IN ('EXPERT_WITNESS','LITIGATION_CONSULTANT','COURT_REPORTING','INTERPRETATION') THEN 'KNOWLEDGE_LANGUAGE_NETWORK'
        WHEN service_family IN ('JANITORIAL','CUSTODIAL','PEST_CONTROL','LAUNDRY_LINEN','GROUNDS_LANDSCAPING') THEN 'LOCAL_SUBCONTRACTABLE_SERVICE'
        WHEN service_family='LODGING_HOTEL' THEN 'TRAVEL_LODGING_AGGREGATION'
        ELSE 'OTHER' END economic_model
      FROM y0 WHERE service_family IS NOT NULL
    """)
    matrix=con.execute("""
      WITH b AS (
       SELECT economic_model,service_family,native_code,native_subcategory,currency,count(*) records,
              count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier,'')) suppliers,
              quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_value,
              median(award_value) FILTER(WHERE award_value>=0) median_value,
              quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_value
       FROM y GROUP BY 1,2,3,4,5
      ), rb0 AS (SELECT economic_model,service_family,native_code,native_subcategory,currency,buyer,count(*) n FROM y WHERE buyer<>'' GROUP BY 1,2,3,4,5,6),
      rb AS (SELECT economic_model,service_family,native_code,native_subcategory,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM rb0 GROUP BY 1,2,3,4,5),
      ss0 AS (SELECT economic_model,service_family,native_code,native_subcategory,currency,supplier,count(*) n FROM y WHERE supplier<>'' GROUP BY 1,2,3,4,5,6),
      ss AS (SELECT economic_model,service_family,native_code,native_subcategory,currency,max(n)*1.0/sum(n) top_supplier_share,count(*) repeatable_suppliers FROM ss0 GROUP BY 1,2,3,4,5)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.top_supplier_share,ss.repeatable_suppliers
      FROM b LEFT JOIN rb USING(economic_model,service_family,native_code,native_subcategory,currency)
      LEFT JOIN ss USING(economic_model,service_family,native_code,native_subcategory,currency)
      ORDER BY service_family,records DESC
    """).fetchall()
    write(out/'market_matrix.csv',['economic_model','service_family','native_code','native_subcategory','currency','records','buyers','suppliers','p25_value','median_value','p75_value','repeat_buyers','top_supplier_share','supplier_rows'],matrix)
    winners=con.execute("""
      SELECT economic_model,service_family,native_code,native_subcategory,currency,supplier,count(*) awards,
             count(*)*1.0/sum(count(*)) over(partition by service_family,native_code,native_subcategory,currency) supplier_share,
             CASE WHEN regexp_matches(coalesce(supplier,''),'(?i)(LLC|INC\.?|CORP|COMPANY|CO\.?|GROUP|ASSOCIATES|SERVICES|SOLUTIONS|PARTNERS|CONSULTING|AGENCY|AGENCIES|ENTERPRISES|LTD|LIMITED|PLLC|LP\b)') THEN 'ORG_LIKE' ELSE 'AMBIGUOUS_OR_INDIVIDUAL_LIKE' END supplier_name_shape
      FROM y WHERE supplier<>'' GROUP BY 1,2,3,4,5,6
      QUALIFY row_number() over(partition by service_family,native_code,native_subcategory,currency order by count(*) desc,supplier)<=20
      ORDER BY service_family,native_code,awards DESC
    """).fetchall();write(out/'top_winners.csv',['economic_model','service_family','native_code','native_subcategory','currency','supplier','awards','supplier_share','supplier_name_shape'],winners)
    buyers=con.execute("""
      SELECT economic_model,service_family,native_code,native_subcategory,currency,buyer,count(*) awards FROM y WHERE buyer<>'' GROUP BY 1,2,3,4,5,6
      QUALIFY row_number() over(partition by service_family,native_code,native_subcategory,currency order by count(*) desc,buyer)<=20
      ORDER BY service_family,native_code,awards DESC
    """).fetchall();write(out/'top_buyers.csv',['economic_model','service_family','native_code','native_subcategory','currency','buyer','awards'],buyers)
    examples=con.execute("""
      SELECT economic_model,service_family,native_code,native_subcategory,currency,tender_id,buyer,supplier,title,award_value FROM y
      QUALIFY row_number() over(partition by service_family,native_code,native_subcategory,currency order by award_value desc nulls last,tender_id)<=12
      ORDER BY service_family,native_code,award_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['economic_model','service_family','native_code','native_subcategory','currency','tender_id','buyer','supplier','title','award_value'],examples)
    broad=con.execute("""
      WITH s AS (SELECT service_family,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier,'')) suppliers,median(award_value) FILTER(WHERE award_value>=0) median_value FROM y GROUP BY 1),
      ss0 AS (SELECT service_family,supplier,count(*) n FROM y WHERE supplier<>'' GROUP BY 1,2),
      ss AS (SELECT service_family,max(n)*1.0/sum(n) top_supplier_share FROM ss0 GROUP BY 1)
      SELECT s.*,ss.top_supplier_share FROM s LEFT JOIN ss USING(service_family) ORDER BY records DESC
    """).fetchall();write(out/'family_summary.csv',['service_family','records','buyers','suppliers','median_value','top_supplier_share'],broad)
    summary={'version':'HISTORICAL_US_AGGREGATOR_SERVICES_V1','archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'classified_rows':con.execute('select count(*) from y').fetchone()[0],'families':dict(con.execute('select service_family,count(*) from y group by 1 order by 2 desc').fetchall()),'grain':'AWARD_FIRST_PROCUREMENT','historical_only':True,'live_used':False,'dce_used':False,'warnings':['USAspending award-first evidence does not prove open competition or current access.','Supplier-name shape is heuristic only, not legal entity classification.','Set-asides, locality, clearances and contract vehicles are not adjudicated here.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# USA Aggregator-Service Historical Decomposition v1','',f"- USAspending records scanned: **{summary['archive_records_scanned']:,}**",f"- classified rows: **{summary['classified_rows']:,}**",'', 'Award-first evidence only. This maps historical market structure for possible expert/language/local-service/lodging aggregation; it does not establish current bidability.','']
    for fam,n,buy,sup,med,share in broad:
      lines += [f'## {fam}',f'- records **{n}** · buyers **{buy}** · suppliers **{sup}** · historical median award **{med if med is not None else "UNKNOWN"} USD** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
