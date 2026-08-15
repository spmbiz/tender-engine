#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from pathlib import Path
import duckdb


def write(path,header,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute('SET threads=4');con.execute("SET memory_limit='5GB'")
    h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=250000,compression='auto')";aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=250000,compression='auto')"
    con.execute(f"""
      CREATE TABLE x AS WITH hh AS (
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,lower(coalesce(Title,'')) title_l,
               coalesce(nullif(NAICS_Code,''),nullif(PSC_Code,''),nullif(CPV_NAICS_or_Local_Code,''),'UNKNOWN') native_code,
               coalesce(nullif(Subcategory,''),nullif(Raw_Spend_Category,''),nullif(Category,''),'UNKNOWN') native_subcategory
        FROM {h}), aa AS (
        SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,upper(coalesce(nullif(Currency,''),'USD')) currency FROM {aw})
      SELECT hh.*,aa.supplier,aa.award_value,aa.currency,
             regexp_replace(regexp_replace(upper(coalesce(aa.supplier,'')),'[^A-Z0-9]','','g'),'(LIMITED|LTD|INCORPORATED|INC|LLC|PLLC|CORPORATION|CORP|COMPANY|CO)$','') supplier_key
      FROM hh LEFT JOIN aa USING(tender_id)
    """)
    con.execute("""
      CREATE TABLE y0 AS SELECT *,CASE
        WHEN regexp_matches(title_l,'(?i)(court reporter services?|court reporting services?|deposition reporting services?|stenographic reporting services?)') THEN 'COURT_REPORTING'
        WHEN regexp_matches(title_l,'(?i)(sign language interpreter|sign language interpretation|deaf.*interpreter|asl interpreter)') THEN 'SIGN_LANGUAGE_INTERPRETATION'
        WHEN regexp_matches(title_l,'(?i)(language interpretation|interpreter services?|interpretation services?|oral interpretation)')
             AND NOT regexp_matches(title_l,'(?i)(radiolog|imag|data interpretation|geophysical|seismic|medical|technical interpretation)') THEN 'GENERAL_LANGUAGE_INTERPRETATION'
        ELSE NULL END svc_family,
        CASE
          WHEN regexp_matches(title_l,'(?i)(video remote|remote video|virtual interpreter|virtual interpretation|virtual court report|virtual court reporter|remote court report|remote court reporter|telephone interpretation|phone interpretation|over[- ]the[- ]phone|telephonic interpretation|\bvri\b|zoom.*interpreter|interpreter.*zoom|remote deposition|virtual deposition)') THEN 'EXPLICIT_REMOTE'
          WHEN regexp_matches(title_l,'(?i)(on[- ]?site|onsite|in[- ]person|face[- ]to[- ]face|at the courthouse|at courthouse|physical presence|on location|local interpreter|local court reporter)') THEN 'EXPLICIT_ONSITE'
          ELSE 'DELIVERY_UNSPECIFIED' END delivery_mode,
        CASE
          WHEN regexp_matches(title_l,'(?i)(deposition)') THEN 'DEPOSITION'
          WHEN regexp_matches(title_l,'(?i)(arbitration)') THEN 'ARBITRATION'
          WHEN regexp_matches(title_l,'(?i)(hearing)') THEN 'HEARING'
          WHEN regexp_matches(title_l,'(?i)(interview)') THEN 'INTERVIEW'
          WHEN regexp_matches(title_l,'(?i)(conference|meeting)') THEN 'MEETING_CONFERENCE'
          ELSE 'USE_CASE_UNSPECIFIED' END use_case
      FROM x
    """)
    con.execute("CREATE TABLE y AS SELECT * FROM y0 WHERE svc_family IS NOT NULL AND coalesce(supplier,'')<>''")
    con.execute("CREATE TABLE sb AS SELECT svc_family,delivery_mode,supplier_key,any_value(supplier) supplier,count(*) awards,count(distinct nullif(buyer,'')) buyers FROM y WHERE supplier_key<>'' GROUP BY 1,2,3")
    con.execute("CREATE TABLE bb AS SELECT svc_family,delivery_mode,buyer,count(*) awards,count(distinct supplier_key) suppliers FROM y WHERE buyer<>'' GROUP BY 1,2,3")
    matrix=con.execute("""
      WITH b AS (
        SELECT svc_family,delivery_mode,use_case,currency,count(*) awards,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier_key,'')) suppliers,
               quantile_cont(award_value,.25) FILTER(WHERE award_value>1) p25_value,median(award_value) FILTER(WHERE award_value>1) median_value,
               quantile_cont(award_value,.75) FILTER(WHERE award_value>1) p75_value
        FROM y GROUP BY 1,2,3,4),
      s0 AS (SELECT svc_family,delivery_mode,use_case,currency,supplier_key,count(*) n FROM y WHERE supplier_key<>'' GROUP BY 1,2,3,4,5),
      s AS (SELECT svc_family,delivery_mode,use_case,currency,max(n)*1.0/sum(n) top_supplier_share FROM s0 GROUP BY 1,2,3,4)
      SELECT b.*,s.top_supplier_share FROM b LEFT JOIN s USING(svc_family,delivery_mode,use_case,currency)
      ORDER BY svc_family,delivery_mode,awards DESC
    """).fetchall()
    write(out/'delivery_usecase_matrix.csv',['svc_family','delivery_mode','use_case','currency','awards','buyers','suppliers','p25_value','median_value','p75_value','top_supplier_share'],matrix)
    modes=con.execute("""
      WITH b AS (SELECT svc_family,delivery_mode,count(*) awards,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier_key,'')) suppliers,median(award_value) FILTER(WHERE award_value>1) median_value FROM y GROUP BY 1,2),
      s0 AS (SELECT svc_family,delivery_mode,supplier_key,count(*) n FROM y WHERE supplier_key<>'' GROUP BY 1,2,3),s AS (SELECT svc_family,delivery_mode,max(n)*1.0/sum(n) top_supplier_share FROM s0 GROUP BY 1,2)
      SELECT b.*,s.top_supplier_share FROM b LEFT JOIN s USING(svc_family,delivery_mode) ORDER BY svc_family,awards DESC
    """).fetchall()
    write(out/'delivery_mode_summary.csv',['svc_family','delivery_mode','awards','buyers','suppliers','median_value','top_supplier_share'],modes)
    repeat=con.execute("""SELECT svc_family,delivery_mode,supplier_key,supplier,awards,buyers FROM sb QUALIFY row_number() over(partition by svc_family,delivery_mode order by buyers desc,awards desc)<=50 ORDER BY svc_family,delivery_mode,buyers DESC,awards DESC""").fetchall()
    write(out/'repeat_suppliers.csv',['svc_family','delivery_mode','supplier_key','supplier','awards','buyers'],repeat)
    buyers=con.execute("""SELECT svc_family,delivery_mode,buyer,awards,suppliers FROM bb QUALIFY row_number() over(partition by svc_family,delivery_mode order by awards desc,buyer)<=50 ORDER BY svc_family,delivery_mode,awards DESC""").fetchall()
    write(out/'repeat_buyers.csv',['svc_family','delivery_mode','buyer','awards','suppliers'],buyers)
    examples=con.execute("""SELECT svc_family,delivery_mode,use_case,tender_id,buyer,supplier,title,award_value,native_code,native_subcategory FROM y QUALIFY row_number() over(partition by svc_family,delivery_mode,use_case order by award_value desc nulls last,tender_id)<=20 ORDER BY svc_family,delivery_mode,use_case,award_value DESC NULLS LAST""").fetchall()
    write(out/'examples.csv',['svc_family','delivery_mode','use_case','tender_id','buyer','supplier','title','award_value','native_code','native_subcategory'],examples)
    summary={'version':'HISTORICAL_US_REMOTE_ONSITE_NETWORK_V1','archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'strict_service_awards':con.execute('select count(*) from y').fetchone()[0],'delivery_modes':dict(con.execute('select delivery_mode,count(*) from y group by 1 order by 2 desc').fetchall()),'family_delivery':{},'historical_only':True,'record_deletion':False,'warning':'Only explicit delivery wording is classified remote or onsite. Absence of wording remains DELIVERY_UNSPECIFIED and must not be imputed.'}
    for fam,mode,n in con.execute('select svc_family,delivery_mode,count(*) from y group by 1,2 order by 1,3 desc').fetchall():summary['family_delivery'].setdefault(fam,{})[mode]=n
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# USA Remote vs Onsite Network Decomposition v1','',f"- USAspending rows scanned **{summary['archive_records_scanned']:,}**",f"- strict court/interpretation awards **{summary['strict_service_awards']:,}**",'', 'Only explicit remote/onsite wording is classified. Everything else remains unknown rather than being guessed.','']
    for fam,mode,n,buy,sup,med,share in modes:lines += [f'## {fam} → {mode}',f'- awards **{n}** · buyers **{buy}** · suppliers **{sup}** · median >$1 award **{med if med is not None else "UNKNOWN"} USD** · top supplier **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
