#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import duckdb


def write(path,header,rows):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(header); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--historical',required=True); ap.add_argument('--awards',required=True); ap.add_argument('--out',required=True)
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(); con.execute('SET threads=4'); con.execute("SET memory_limit='5GB'")
    h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=250000,compression='auto')"
    aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=250000,compression='auto')"

    con.execute(f"""
      CREATE TABLE x AS
      WITH hh AS (
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,
               coalesce(nullif(NAICS_Code,''),nullif(PSC_Code,''),nullif(CPV_NAICS_or_Local_Code,''),'UNKNOWN') native_code,
               coalesce(nullif(Subcategory,''),nullif(Raw_Spend_Category,''),nullif(Category,''),'UNKNOWN') native_subcategory,
               lower(coalesce(Title,'')) title_l
        FROM {h}
      ), aa AS (
        SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,upper(coalesce(nullif(Currency,''),'USD')) currency
        FROM {aw}
      )
      SELECT hh.*,aa.supplier,aa.award_value,aa.currency,
             regexp_replace(regexp_replace(upper(coalesce(aa.supplier,'')),'[^A-Z0-9]','','g'),'(LIMITED|LTD|INCORPORATED|INC|LLC|PLLC|CORPORATION|CORP|COMPANY|CO)$','') supplier_key
      FROM hh LEFT JOIN aa USING(tender_id)
    """)

    con.execute("""
      CREATE TABLE y0 AS SELECT *,CASE
        WHEN regexp_matches(title_l,'(?i)(expert witness|expert witness services|expert services.*witness)') THEN 'EXPERT_WITNESS'
        WHEN regexp_matches(title_l,'(?i)(litigation consultant|litigation consulting|litigation support services)') THEN 'LITIGATION_SUPPORT'
        WHEN regexp_matches(title_l,'(?i)(court reporter services?|court reporting services?|deposition reporting services?|stenographic reporting services?)') THEN 'COURT_REPORTING'
        WHEN regexp_matches(title_l,'(?i)(sign language interpreter|sign language interpretation|deaf.*interpreter|asl interpreter)') THEN 'SIGN_LANGUAGE_INTERPRETATION'
        WHEN regexp_matches(title_l,'(?i)(phone interpretation|telephone interpretation|video remote interpretation|remote interpretation|over[- ]the[- ]phone interpretation)') THEN 'REMOTE_LANGUAGE_INTERPRETATION'
        WHEN regexp_matches(title_l,'(?i)(language interpretation|interpreter services?|interpretation services?|oral interpretation)')
             AND NOT regexp_matches(title_l,'(?i)(radiolog|imag|data interpretation|geophysical|seismic|medical|technical interpretation)') THEN 'GENERAL_LANGUAGE_INTERPRETATION'
        ELSE NULL END family
      FROM x
    """)
    con.execute("CREATE TABLE y AS SELECT * FROM y0 WHERE family IS NOT NULL AND coalesce(supplier,'')<>''")

    con.execute("""
      CREATE TABLE supplier_stats AS
      WITH s AS (
        SELECT family,supplier_key,any_value(supplier) supplier,count(*) awards,count(distinct nullif(buyer,'')) buyers,
               median(award_value) FILTER(WHERE award_value>=0) median_award
        FROM y WHERE supplier_key<>'' GROUP BY 1,2
      ), sb AS (
        SELECT family,supplier_key,buyer,count(*) n FROM y WHERE supplier_key<>'' AND buyer<>'' GROUP BY 1,2,3
      ), conc AS (
        SELECT family,supplier_key,max(n)*1.0/sum(n) top_buyer_share FROM sb GROUP BY 1,2
      )
      SELECT s.*,conc.top_buyer_share,
        CASE
          WHEN family='COURT_REPORTING' AND regexp_matches(upper(supplier),'(REPORT|DEPOSITION|LEGAL SUPPORT|STENOGRAPH|CAPTION|ESCRIBER)') THEN 'STRONG_NETWORK_OR_AGENCY_SIGNAL'
          WHEN family IN ('GENERAL_LANGUAGE_INTERPRETATION','REMOTE_LANGUAGE_INTERPRETATION','SIGN_LANGUAGE_INTERPRETATION') AND regexp_matches(upper(supplier),'(LANGUAGE|INTERPRET|TRANSLAT|LINGUIST|DEAF|HEARING|COMMUNICATION)') THEN 'STRONG_NETWORK_OR_AGENCY_SIGNAL'
          WHEN family IN ('EXPERT_WITNESS','LITIGATION_SUPPORT') AND regexp_matches(upper(supplier),'(EXPERTCONNECT|EXPERT NETWORK|LITIGATION SUPPORT|LEGAL SUPPORT|EXPERT SERVICES)') THEN 'STRONG_NETWORK_OR_AGENCY_SIGNAL'
          WHEN regexp_matches(upper(supplier),'(LLC|INC\.?|CORP|CORPORATION|COMPANY| CO\.?|GROUP|ASSOCIATES|SERVICES|SOLUTIONS|PARTNERS|CONSULTING|AGENCY|ENTERPRISES|LTD|LIMITED|PLLC)') AND s.buyers>=3 THEN 'REPEAT_ORG_AGENCY_PLAUSIBLE'
          WHEN regexp_matches(upper(supplier),'(LLC|INC\.?|CORP|CORPORATION|COMPANY| CO\.?|GROUP|ASSOCIATES|SERVICES|SOLUTIONS|PARTNERS|CONSULTING|AGENCY|ENTERPRISES|LTD|LIMITED|PLLC)') THEN 'ORG_OR_FIRM_SINGLE_OR_FEW_BUYERS'
          ELSE 'INDIVIDUAL_OR_AMBIGUOUS'
        END supplier_shape
      FROM s LEFT JOIN conc USING(family,supplier_key)
    """)

    con.execute("""
      CREATE TABLE enriched AS
      SELECT y.*,s.awards supplier_awards,s.buyers supplier_buyers,s.median_award supplier_median_award,s.top_buyer_share,s.supplier_shape
      FROM y JOIN supplier_stats s USING(family,supplier_key)
    """)

    family=con.execute("""
      WITH b AS (
        SELECT family,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct supplier_key) suppliers,
               median(award_value) FILTER(WHERE award_value>=0) median_award,
               quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_award,
               quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_award
        FROM enriched GROUP BY 1
      ), sc AS (
        SELECT family,
               count(*) FILTER(WHERE buyers>=2) multi_buyer_suppliers,
               count(*) FILTER(WHERE buyers>=3) repeat_3plus_buyer_suppliers,
               median(buyers) median_buyers_per_supplier,
               max(awards)*1.0/nullif(sum(awards),0) top_supplier_share
        FROM supplier_stats GROUP BY 1
      ), sh AS (
        SELECT family,
          sum(CASE WHEN supplier_shape='STRONG_NETWORK_OR_AGENCY_SIGNAL' THEN 1 ELSE 0 END)*1.0/count(*) strong_network_award_share,
          sum(CASE WHEN supplier_shape IN ('STRONG_NETWORK_OR_AGENCY_SIGNAL','REPEAT_ORG_AGENCY_PLAUSIBLE') THEN 1 ELSE 0 END)*1.0/count(*) repeat_org_or_network_award_share,
          sum(CASE WHEN supplier_shape='INDIVIDUAL_OR_AMBIGUOUS' THEN 1 ELSE 0 END)*1.0/count(*) individual_ambiguous_award_share
        FROM enriched GROUP BY 1
      )
      SELECT b.*,sc.multi_buyer_suppliers,sc.repeat_3plus_buyer_suppliers,sc.median_buyers_per_supplier,sc.top_supplier_share,
             sh.strong_network_award_share,sh.repeat_org_or_network_award_share,sh.individual_ambiguous_award_share
      FROM b JOIN sc USING(family) JOIN sh USING(family) ORDER BY records DESC
    """).fetchall()
    write(out/'family_intermediation_scorecard.csv',['family','records','buyers','suppliers','median_award','p25_award','p75_award','multi_buyer_suppliers','repeat_3plus_buyer_suppliers','median_buyers_per_supplier','top_supplier_share','strong_network_award_share','repeat_org_or_network_award_share','individual_ambiguous_award_share'],family)

    suppliers=con.execute("""
      SELECT family,supplier_key,supplier,awards,buyers,median_award,top_buyer_share,supplier_shape
      FROM supplier_stats
      QUALIFY row_number() over(partition by family order by awards desc,buyers desc,supplier)<=100
      ORDER BY family,awards DESC,buyers DESC
    """).fetchall()
    write(out/'supplier_archetypes.csv',['family','supplier_key','supplier','awards','buyers','median_award','top_buyer_share','supplier_shape'],suppliers)

    buyers=con.execute("""
      SELECT family,buyer,count(*) awards,count(distinct supplier_key) suppliers,median(award_value) FILTER(WHERE award_value>=0) median_award
      FROM enriched WHERE buyer<>'' GROUP BY 1,2
      QUALIFY row_number() over(partition by family order by count(*) desc,buyer)<=50
      ORDER BY family,awards DESC
    """).fetchall()
    write(out/'top_buyers.csv',['family','buyer','awards','suppliers','median_award'],buyers)

    examples=con.execute("""
      SELECT family,supplier_shape,tender_id,buyer,supplier,title,award_value,native_code,native_subcategory,supplier_awards,supplier_buyers,top_buyer_share
      FROM enriched
      QUALIFY row_number() over(partition by family,supplier_shape order by supplier_buyers desc,supplier_awards desc,award_value desc nulls last,tender_id)<=20
      ORDER BY family,supplier_shape,supplier_buyers DESC,supplier_awards DESC
    """).fetchall()
    write(out/'examples.csv',['family','supplier_shape','tender_id','buyer','supplier','title','award_value','native_code','native_subcategory','supplier_awards','supplier_buyers','top_buyer_share'],examples)

    summary={
      'version':'HISTORICAL_US_NETWORK_INTERMEDIARY_ECONOMICS_V3_1',
      'archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],
      'strict_title_rows':con.execute('select count(*) from enriched').fetchone()[0],
      'families':dict(con.execute('select family,count(*) from enriched group by 1 order by 2 desc').fetchall()),
      'grain':'AWARD_FIRST_PROCUREMENT','historical_only':True,'live_used':False,'dce_used':False,'record_deletion':False,
      'supersession':'v3.0 compute failed only in final supplier-count aggregation syntax; no v3.0 USA output was promoted.',
      'warning':'Supplier business shape is a historical heuristic based on name and multi-buyer behavior; it does not prove subcontracting, brokerage, licensing, set-aside access or current bidability.'
    }
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# USA Network / Intermediary Economics v3.1','',f"- USAspending records scanned **{summary['archive_records_scanned']:,}**",f"- strict title-led network-service award rows **{summary['strict_title_rows']:,}**",'', 'This analysis asks whether repeat multi-buyer organizations are empirically present in expert, court-reporting and interpretation markets. It does not infer current eligibility.','']
    for r in family:
        fam,n,buy,sup,med,p25,p75,multi,three,mbps,top,strong,org,ind=r
        lines += [f'## {fam}',f'- awards **{n}** · buyers **{buy}** · suppliers **{sup}** · median award **{med if med is not None else "UNKNOWN"} USD**',f'- suppliers serving ≥2 buyers **{multi}** · ≥3 buyers **{three}** · top supplier share **{round(100*top,1) if top is not None else "UNKNOWN"}%**',f'- strong network/agency-name award share **{round(100*strong,1)}%** · strong+repeat-org share **{round(100*org,1)}%** · individual/ambiguous share **{round(100*ind,1)}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__': main()
