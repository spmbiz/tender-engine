#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import duckdb

def write(path,header,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute('SET threads=4');con.execute("SET memory_limit='5GB'")
    h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=200000,compression='auto')";aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=200000,compression='auto')"
    con.execute(f"""
      CREATE TABLE x AS WITH hh AS (
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,coalesce(Description,'') description,coalesce(Subcategory,'') subcategory,coalesce(Category,'') category,
        lower(coalesce(Title,'')) title_l,lower(coalesce(Description,'')) description_l,lower(concat_ws(' ',coalesce(Title,''),coalesce(Description,''),coalesce(Subcategory,''),coalesce(Category,''))) txt FROM {h}),
      aa AS (SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,upper(coalesce(nullif(Currency,''),'AUD')) currency FROM {aw})
      SELECT hh.*,aa.supplier,aa.award_value,aa.currency,regexp_replace(regexp_replace(upper(coalesce(aa.supplier,'')),'[^A-Z0-9]','','g'),'(PTYLIMITED|PTYLTD|PROPRIETARYLIMITED|LIMITED|LTD|INCORPORATED|INC|LLC)$','') supplier_key FROM hh LEFT JOIN aa USING(tender_id)
    """)
    con.execute("""
      CREATE TABLE c0 AS SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(test and evaluation|test & evaluation|testing and evaluation|technical evaluation services|weapon.*evaluation|systems? test.*evaluation)') THEN 'TECHNICAL_TEST_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(gateway review|assurance review|project assurance review|program assurance review|programme assurance review|project health check review|program health check review)') THEN 'PROJECT_PROGRAM_ASSURANCE'
        WHEN regexp_matches(txt,'(?i)(program evaluation|programme evaluation|evaluation of (the )?.{0,100}(program|programme|initiative|service|scheme|policy)|impact evaluation|outcome evaluation|process evaluation|policy evaluation|service evaluation)') THEN 'POLICY_PROGRAM_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(research evaluation|evaluation research|monitoring and evaluation|monitoring & evaluation|evaluation framework)') THEN 'RESEARCH_MONITORING_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(independent review|independent assessment|specialist review|external review|peer review)') THEN 'INDEPENDENT_REVIEW'
        WHEN regexp_matches(txt,'(?i)(evaluation services?)') THEN 'GENERIC_EVALUATION_UNRESOLVED'
        ELSE NULL END review_family,
        CASE WHEN regexp_matches(title_l,'(?i)(test and evaluation|assurance review|program evaluation|programme evaluation|impact evaluation|outcome evaluation|process evaluation|independent review|independent assessment|specialist review|external review|peer review|monitoring and evaluation|evaluation framework)') THEN 'TITLE_SIGNAL'
             WHEN regexp_matches(description_l,'(?i)(test and evaluation|assurance review|program evaluation|programme evaluation|impact evaluation|outcome evaluation|process evaluation|independent review|independent assessment|specialist review|external review|peer review|monitoring and evaluation|monitoring & evaluation|evaluation framework)') THEN 'DESCRIPTION_SIGNAL'
             ELSE 'CATEGORY_OR_COMBINED_SIGNAL' END signal_source
      FROM x
    """)
    con.execute("""
      CREATE TABLE y AS SELECT *,CASE
        WHEN review_family='TECHNICAL_TEST_EVALUATION' THEN 'TECHNICAL_SPECIALIST_HARD'
        WHEN review_family='GENERIC_EVALUATION_UNRESOLVED' THEN 'UNRESOLVED'
        WHEN regexp_matches(txt,'(?i)(engineer|engineering|dam safety|geotechnical|structural|medical evaluation|clinical|legal|lawyer|financial audit|accounting standard|actuar|cybersecurity|security clearance|accreditation|registered professional|licensed|licenced|certified auditor)') THEN 'SPECIALIST_CREDENTIAL_HEAVY'
        WHEN regexp_matches(txt,'(?i)(site inspection|on[- ]?site|onsite|field inspection|physical inspection|site visit|at premises)') THEN 'LOCATION_OR_PHYSICAL_HEAVY'
        WHEN regexp_matches(txt,'(?i)(interviews?|focus groups?|stakeholder engagement|community engagement|workshops?|facilitat|survey participants?|consultations?)') THEN 'HUMAN_RESEARCH_HEAVY'
        ELSE 'REMOTE_ANALYTICAL_PLAUSIBLE' END delivery_risk,
        CASE WHEN regexp_matches(txt,'(?i)(report|review report|evaluation report|findings|recommendations|assessment report|briefing|analysis|evidence|desktop review|document review)') THEN 'REPORT_ANALYSIS_DELIVERABLE'
             WHEN regexp_matches(txt,'(?i)(framework|methodology|evaluation plan|assurance plan)') THEN 'FRAMEWORK_METHOD_DELIVERABLE' ELSE 'UNRESOLVED_DELIVERABLE' END deliverable_type
      FROM c0 WHERE review_family IS NOT NULL
    """)
    matrix=con.execute("""
      WITH b AS (SELECT review_family,signal_source,delivery_risk,deliverable_type,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier_key,'')) supplier_keys,quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_value,median(award_value) FILTER(WHERE award_value>=0) median_value,quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_value FROM y GROUP BY 1,2,3,4,5),
      rb0 AS (SELECT review_family,signal_source,delivery_risk,deliverable_type,currency,buyer,count(*) n FROM y WHERE buyer<>'' GROUP BY 1,2,3,4,5,6),rb AS (SELECT review_family,signal_source,delivery_risk,deliverable_type,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM rb0 GROUP BY 1,2,3,4,5),
      ss0 AS (SELECT review_family,signal_source,delivery_risk,deliverable_type,currency,supplier_key,count(*) n FROM y WHERE supplier_key<>'' GROUP BY 1,2,3,4,5,6),ss AS (SELECT review_family,signal_source,delivery_risk,deliverable_type,currency,max(n)*1.0/sum(n) top_supplier_share FROM ss0 GROUP BY 1,2,3,4,5)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.top_supplier_share FROM b LEFT JOIN rb USING(review_family,signal_source,delivery_risk,deliverable_type,currency) LEFT JOIN ss USING(review_family,signal_source,delivery_risk,deliverable_type,currency) ORDER BY review_family,delivery_risk,records DESC
    """).fetchall()
    write(out/'market_matrix.csv',['review_family','signal_source','delivery_risk','deliverable_type','currency','records','buyers','supplier_keys','p25_value','median_value','p75_value','repeat_buyers','top_supplier_share'],matrix)
    family=con.execute("""
      WITH b AS (SELECT review_family,delivery_risk,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier_key,'')) suppliers,median(award_value) FILTER(WHERE award_value>=0) median_value FROM y GROUP BY 1,2),s0 AS (SELECT review_family,delivery_risk,supplier_key,count(*) n FROM y WHERE supplier_key<>'' GROUP BY 1,2,3),s AS (SELECT review_family,delivery_risk,max(n)*1.0/sum(n) top_supplier_share FROM s0 GROUP BY 1,2)
      SELECT b.*,s.top_supplier_share FROM b LEFT JOIN s USING(review_family,delivery_risk) ORDER BY review_family,records DESC
    """).fetchall()
    write(out/'family_risk_summary.csv',['review_family','delivery_risk','records','buyers','suppliers','median_value','top_supplier_share'],family)
    winners=con.execute("""SELECT review_family,delivery_risk,supplier_key,any_value(supplier) supplier,count(*) awards,count(distinct nullif(buyer,'')) buyers,count(*)*1.0/sum(count(*)) over(partition by review_family,delivery_risk) supplier_share FROM y WHERE supplier_key<>'' GROUP BY 1,2,3 QUALIFY row_number() over(partition by review_family,delivery_risk order by count(*) desc,supplier_key)<=40 ORDER BY review_family,delivery_risk,awards DESC""").fetchall()
    write(out/'top_winners.csv',['review_family','delivery_risk','supplier_key','supplier','awards','buyers','supplier_share'],winners)
    examples=con.execute("""SELECT review_family,signal_source,delivery_risk,deliverable_type,currency,tender_id,buyer,supplier,title,substr(description,1,1800) description_excerpt,award_value,subcategory,category FROM y QUALIFY row_number() over(partition by review_family,delivery_risk order by award_value desc nulls last,tender_id)<=30 ORDER BY review_family,delivery_risk,award_value DESC NULLS LAST""").fetchall()
    write(out/'examples.csv',['review_family','signal_source','delivery_risk','deliverable_type','currency','tender_id','buyer','supplier','title','description_excerpt','award_value','subcategory','category'],examples)
    summary={'version':'HISTORICAL_AU_REVIEW_EVALUATION_PRECISION_V3_2','archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'strict_semantic_rows':con.execute('select count(*) from y').fetchone()[0],'families':dict(con.execute('select review_family,count(*) from y group by 1 order by 2 desc').fetchall()),'risk_classes':dict(con.execute('select delivery_risk,count(*) from y group by 1 order by 2 desc').fetchall()),'grain':'AWARD_FIRST_PROCUREMENT','historical_only':True,'record_deletion':False,'live_used':False,'dce_used':False,'supersession':'v3.1 PROGRAM_EVALUATION is superseded by v3.2 because semantic QA found Defence technical Test and Evaluation contamination. v3.2 splits policy/program evaluation, technical test/evaluation and generic unresolved evaluation.','warning':'Remote analytical classification is triage only; panels, credentials, locality and current access remain unknown.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Australia Review / Evaluation Precision v3.2','',f"- records scanned **{summary['archive_records_scanned']:,}**",f"- strict review/evaluation rows **{summary['strict_semantic_rows']:,}**",'', 'v3.2 explicitly separates policy/program evaluation from technical Test and Evaluation and generic unresolved evaluation.','']
    for fam,risk,n,buy,sup,med,share in family:lines += [f'## {fam} → {risk}',f'- awards **{n}** · buyers **{buy}** · suppliers **{sup}** · median **{med if med is not None else "UNKNOWN"} AUD** · top supplier **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
