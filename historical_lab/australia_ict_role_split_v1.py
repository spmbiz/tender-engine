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
    con=duckdb.connect();con.execute('SET threads=4')
    h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=200000,compression='auto')"
    aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=200000,compression='auto')"
    con.execute(f"""
      CREATE TABLE x AS
      WITH hh AS (
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,
               lower(concat_ws(' ',coalesce(Title,''),coalesce(Description,''),coalesce(Subcategory,''),coalesce(Category,''))) txt
        FROM {h}
      ), aa AS (
        SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,
               upper(coalesce(nullif(Currency,''),'AUD')) currency
        FROM {aw}
      ) SELECT hh.*,aa.supplier,aa.award_value,aa.currency FROM hh LEFT JOIN aa USING(tender_id)
    """)
    con.execute("""
      CREATE TABLE r0 AS
      SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(business analyst|business analysis)') THEN 'BUSINESS_ANALYST'
        WHEN regexp_matches(txt,'(?i)(data scientist|data science)') THEN 'DATA_SCIENTIST'
        WHEN regexp_matches(txt,'(?i)(data engineer|data engineering)') THEN 'DATA_ENGINEER'
        WHEN regexp_matches(txt,'(?i)(data analyst|data analytics|analytics specialist)') THEN 'DATA_ANALYST_ANALYTICS'
        WHEN regexp_matches(txt,'(?i)(cyber security|cybersecurity|security analyst|security architect|penetration tester|soc analyst)') THEN 'CYBER_SECURITY'
        WHEN regexp_matches(txt,'(?i)(software developer|software engineer|application developer|web developer|full stack|full-stack|frontend developer|front-end developer|backend developer|back-end developer)') THEN 'SOFTWARE_DEVELOPER_ENGINEER'
        WHEN regexp_matches(txt,'(?i)(solution architect|solutions architect|technical architect|enterprise architect)') THEN 'ARCHITECT'
        WHEN regexp_matches(txt,'(?i)(technical writer|technical writing|documentation specialist)') THEN 'TECHNICAL_WRITER'
        WHEN regexp_matches(txt,'(?i)(project manager|project management specialist|ict project manager|it project manager)') THEN 'PROJECT_MANAGER'
        WHEN regexp_matches(txt,'(?i)(program manager|programme manager|program management specialist|programme management specialist)') THEN 'PROGRAM_MANAGER'
        WHEN regexp_matches(txt,'(?i)(scrum master|agile coach|delivery manager)') THEN 'AGILE_DELIVERY'
        WHEN regexp_matches(txt,'(?i)(test analyst|software tester|test engineer|quality assurance analyst|qa analyst)') THEN 'TEST_QA'
        WHEN regexp_matches(txt,'(?i)(systems administrator|system administrator|network administrator|network engineer|infrastructure engineer|cloud engineer|devops engineer)') THEN 'INFRA_CLOUD_DEVOPS'
        WHEN regexp_matches(txt,'(?i)(service desk|help desk|desktop support|ict support|it support)') THEN 'IT_SUPPORT_DESK'
        ELSE NULL END role_family
      FROM x
    """)
    con.execute("CREATE TABLE r AS SELECT * FROM r0 WHERE role_family IS NOT NULL")
    matrix=con.execute("""
      WITH b AS (
       SELECT role_family,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier,'')) suppliers,
              quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_value,
              median(award_value) FILTER(WHERE award_value>=0) median_value,
              quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_value
       FROM r GROUP BY 1,2),
      rb0 AS (SELECT role_family,currency,buyer,count(*) n FROM r WHERE buyer<>'' GROUP BY 1,2,3),
      rb AS (SELECT role_family,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM rb0 GROUP BY 1,2),
      ss0 AS (SELECT role_family,currency,supplier,count(*) n FROM r WHERE supplier<>'' GROUP BY 1,2,3),
      ss AS (SELECT role_family,currency,max(n)*1.0/sum(n) top_supplier_share FROM ss0 GROUP BY 1,2)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.top_supplier_share
      FROM b LEFT JOIN rb USING(role_family,currency) LEFT JOIN ss USING(role_family,currency)
      ORDER BY records DESC
    """).fetchall()
    write(out/'role_matrix.csv',['role_family','currency','records','buyers','suppliers','p25_value','median_value','p75_value','repeat_buyers','top_supplier_share'],matrix)
    winners=con.execute("""
      SELECT role_family,currency,supplier,count(*) awards,count(*)*1.0/sum(count(*)) over(partition by role_family,currency) supplier_share
      FROM r WHERE supplier<>'' GROUP BY 1,2,3
      QUALIFY row_number() over(partition by role_family,currency order by count(*) desc,supplier)<=10
      ORDER BY role_family,awards DESC
    """).fetchall();write(out/'top_winners.csv',['role_family','currency','supplier','awards','supplier_share'],winners)
    buyers=con.execute("""
      SELECT role_family,currency,buyer,count(*) awards FROM r WHERE buyer<>'' GROUP BY 1,2,3
      QUALIFY row_number() over(partition by role_family,currency order by count(*) desc,buyer)<=10
      ORDER BY role_family,awards DESC
    """).fetchall();write(out/'top_buyers.csv',['role_family','currency','buyer','awards'],buyers)
    examples=con.execute("""
      SELECT role_family,currency,tender_id,buyer,supplier,title,award_value FROM r
      QUALIFY row_number() over(partition by role_family,currency order by award_value desc nulls last,tender_id)<=6
      ORDER BY role_family,award_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['role_family','currency','tender_id','buyer','supplier','title','award_value'],examples)
    summary={'archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'role_matches':con.execute('select count(*) from r').fetchone()[0],'role_families':len(matrix),'grain':'AWARD_FIRST_PROCUREMENT','historical_only':True,'live_used':False,'dce_used':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    lines=['# Australia ICT / Digital Talent Role Split v1','',f"- AusTender records scanned: **{summary['archive_records_scanned']:,}**",f"- title/scope role matches: **{summary['role_matches']:,}**",f"- role families: **{summary['role_families']:,}**",'', 'Award-first historical evidence only. Supplier fragmentation and buyer recurrence do not prove present open-tender access.','']
    for r in matrix:
        role,cur,n,buy,sup,p25,med,p75,rb,share=r
        lines += [f'## {role}',f'- records **{n}** · buyers **{buy}** · repeat buyers **{rb}** · suppliers **{sup}** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**',f'- {cur} p25/median/p75 **{p25 if p25 is not None else "UNKNOWN"} / {med if med is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':main()
