#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from pathlib import Path
import duckdb


def write(path,header,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute('SET threads=4')
    rel=f"read_csv_auto('{a.input}',header=true,all_varchar=true,sample_size=200000,compression='auto')"
    con.execute(f"""
    CREATE TABLE x AS
    SELECT Historical_Tender_ID tender_id,Agency_Name buyer,Supplier_Name supplier,Title title,
           coalesce(nullif(Subcategory,''),nullif(Raw_Spend_Category,''),nullif(Category,''),'UNKNOWN') native_subcategory,
           try_cast(Award_Value as double) award_value,
           upper(coalesce(nullif(Currency,''),'AUD')) currency,
           lower(concat_ws(' ',coalesce(Title,''),coalesce(Description,''),coalesce(Subcategory,''),coalesce(Raw_Spend_Category,''))) txt
    FROM {rel}
    """)
    con.execute("""
    CREATE TABLE scoped AS
    SELECT *,CASE
      WHEN regexp_matches(txt,'(?i)(ict labour hire|it labour hire|ict contractor|ict staff|business analyst|software developer|developer|data analyst|cyber.*(staff|consult)|technical writer)') THEN 'ICT_DIGITAL_TALENT'
      WHEN regexp_matches(txt,'(?i)(temporary personnel|temporary staff|labou?r hire|contracted services|staffing)') THEN 'GENERAL_STAFFING'
      WHEN regexp_matches(txt,'(?i)(project management|project manager|program management|programme management|program manager|pmo)') THEN 'PROJECT_PROGRAM_TALENT'
      WHEN regexp_matches(txt,'(?i)(professional services|consulting services|consultancy services|business support services|support services)') THEN 'PROFESSIONAL_SUPPORT'
      WHEN regexp_matches(txt,'(?i)(software support services|application support|ict services|it support services)') THEN 'IT_MANAGED_SUPPORT'
      ELSE NULL END family
    FROM x
    """)
    con.execute("CREATE TABLE y AS SELECT * FROM scoped WHERE family IS NOT NULL")
    matrix=con.execute("""
    WITH b AS (
      SELECT family,native_subcategory,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier,'')) suppliers,
             quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_value,
             median(award_value) FILTER(WHERE award_value>=0) median_value,
             quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_value
      FROM y GROUP BY 1,2,3
    ), rb0 AS (SELECT family,native_subcategory,currency,buyer,count(*) n FROM y WHERE buyer<>'' GROUP BY 1,2,3,4),
    rb AS (SELECT family,native_subcategory,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM rb0 GROUP BY 1,2,3),
    ss0 AS (SELECT family,native_subcategory,currency,supplier,count(*) n FROM y WHERE supplier<>'' GROUP BY 1,2,3,4),
    ss AS (SELECT family,native_subcategory,currency,max(n)*1.0/sum(n) top_supplier_share FROM ss0 GROUP BY 1,2,3)
    SELECT b.*,coalesce(rb.repeat_buyers,0),ss.top_supplier_share
    FROM b LEFT JOIN rb USING(family,native_subcategory,currency) LEFT JOIN ss USING(family,native_subcategory,currency)
    ORDER BY records DESC,median_value DESC NULLS LAST
    """).fetchall()
    write(out/'market_matrix.csv',['family','native_subcategory','currency','records','buyers','suppliers','p25_value','median_value','p75_value','repeat_buyers','top_supplier_share'],matrix)
    winners=con.execute("""
      SELECT family,native_subcategory,currency,supplier,count(*) awards,
             count(*)*1.0/sum(count(*)) over(partition by family,native_subcategory,currency) supplier_share
      FROM y WHERE supplier<>'' GROUP BY 1,2,3,4
      QUALIFY row_number() over(partition by family,native_subcategory,currency order by count(*) desc,supplier)<=10
      ORDER BY family,native_subcategory,awards DESC
    """).fetchall()
    write(out/'top_winners.csv',['family','native_subcategory','currency','supplier','awards','supplier_share'],winners)
    buyers=con.execute("""
      SELECT family,native_subcategory,currency,buyer,count(*) awards
      FROM y WHERE buyer<>'' GROUP BY 1,2,3,4
      QUALIFY row_number() over(partition by family,native_subcategory,currency order by count(*) desc,buyer)<=10
      ORDER BY family,native_subcategory,awards DESC
    """).fetchall()
    write(out/'top_buyers.csv',['family','native_subcategory','currency','buyer','awards'],buyers)
    examples=con.execute("""
      SELECT family,native_subcategory,currency,tender_id,buyer,supplier,title,award_value
      FROM y QUALIFY row_number() over(partition by family,native_subcategory,currency order by award_value desc nulls last,tender_id)<=5
      ORDER BY family,native_subcategory,award_value DESC NULLS LAST
    """).fetchall()
    write(out/'examples.csv',['family','native_subcategory','currency','tender_id','buyer','supplier','title','award_value'],examples)
    summary={'archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'scoped_records':con.execute('select count(*) from y').fetchone()[0],'submarkets':len(matrix),'historical_only':True,'grain':'AWARD_FIRST_PROCUREMENT','live_used':False,'dce_used':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    lines=['# Australia Staffing / Consulting Atlas v1','',f"- archive records scanned: **{summary['archive_records_scanned']:,}**",f"- scoped staffing/support awards: **{summary['scoped_records']:,}**",f"- submarkets: **{summary['submarkets']:,}**",'', 'AusTender evidence is award-first. Supplier fragmentation and buyer recurrence are historical demand evidence; they do not prove current open competition.','']
    for r in matrix[:100]:
        fam,sub,cur,n,buy,sup,p25,med,p75,rb,share=r
        lines += [f'## {fam} — {sub}',f'- records **{n}** · buyers **{buy}** · repeat buyers **{rb}** · suppliers **{sup}** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**',f'- {cur} p25/median/p75: **{p25 if p25 is not None else "UNKNOWN"} / {med if med is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':main()
