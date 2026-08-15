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
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,coalesce(Description,'') description,
               lower(concat_ws(' ',coalesce(Title,''),coalesce(Description,''),coalesce(Subcategory,''),coalesce(Category,''))) txt
        FROM {h}),aa AS (
        SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,upper(coalesce(nullif(Currency,''),'AUD')) currency FROM {aw})
      SELECT hh.*,aa.supplier,aa.award_value,aa.currency,
             regexp_replace(regexp_replace(upper(coalesce(aa.supplier,'')),'[^A-Z0-9]','','g'),'(PTYLIMITED|PTYLTD|PROPRIETARYLIMITED|LIMITED|LTD|INCORPORATED|INC|LLC)$','') supplier_key
      FROM hh LEFT JOIN aa USING(tender_id)
    """)
    con.execute("""
      CREATE TABLE y0 AS SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(test and evaluation|test & evaluation|testing and evaluation|technical evaluation services|weapon.*evaluation|systems? test.*evaluation)') THEN 'TECHNICAL_TEST_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(gateway review|assurance review|project assurance review|program assurance review|programme assurance review|project health check review|program health check review)') THEN 'PROJECT_PROGRAM_ASSURANCE'
        WHEN regexp_matches(txt,'(?i)(program evaluation|programme evaluation|evaluation of (the )?.{0,100}(program|programme|initiative|service|scheme|policy)|impact evaluation|outcome evaluation|process evaluation|policy evaluation|service evaluation)') THEN 'POLICY_PROGRAM_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(research evaluation|evaluation research|monitoring and evaluation|monitoring & evaluation|evaluation framework)') THEN 'RESEARCH_MONITORING_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(independent review|independent assessment|specialist review|external review|peer review)') THEN 'INDEPENDENT_REVIEW'
        ELSE NULL END review_family
      FROM x
    """)
    con.execute("""
      CREATE TABLE y AS SELECT *,
        regexp_matches(txt,'(?i)(desk research|desktop research|document review|literature review|secondary research|records review|evidence review|data analysis|quantitative analysis|qualitative analysis)') desk_analysis,
        regexp_matches(txt,'(?i)(interviews?|stakeholder interviews?|key informant|consultations?)') interview_consult,
        regexp_matches(txt,'(?i)(survey|questionnaire|polling|respondent)') survey_work,
        regexp_matches(txt,'(?i)(focus groups?|workshops?|facilitat|roundtable)') workshop_focus,
        regexp_matches(txt,'(?i)(community engagement|stakeholder engagement|engagement plan|outreach)') stakeholder_engagement,
        regexp_matches(txt,'(?i)(fieldwork|field work|site visit|site inspection|on[- ]?site|onsite|physical inspection)') field_physical,
        regexp_matches(txt,'(?i)(report|findings|recommendations|discussion paper|evaluation report|review report|final report|briefing)') report_deliverable,
        regexp_matches(txt,'(?i)(framework|methodology|evaluation plan|logic model|theory of change|evaluation design)') method_framework,
        regexp_matches(txt,'(?i)(engineer|engineering|medical|clinical|lawyer|legal advice|actuar|registered professional|licensed|licenced|certified|accredit|security clearance)') specialist_credential
      FROM y0 WHERE review_family IN ('POLICY_PROGRAM_EVALUATION','INDEPENDENT_REVIEW','RESEARCH_MONITORING_EVALUATION','PROJECT_PROGRAM_ASSURANCE')
    """)
    con.execute("""
      CREATE TABLE z AS SELECT *,CASE
        WHEN specialist_credential THEN 'SPECIALIST_SIGNOFF_OR_CREDENTIAL'
        WHEN field_physical THEN 'FIELD_OR_PHYSICAL'
        WHEN stakeholder_engagement OR interview_consult OR workshop_focus OR survey_work THEN 'HUMAN_RESEARCH_COMPONENT'
        WHEN report_deliverable OR desk_analysis OR method_framework THEN 'DESK_ANALYTICAL_DOMINANT_PLAUSIBLE'
        ELSE 'DELIVERABLE_UNRESOLVED' END delivery_bundle
      FROM y
    """)
    matrix=con.execute("""
      WITH b AS (SELECT review_family,delivery_bundle,currency,count(*) awards,count(distinct nullif(buyer,'')) buyers,count(distinct nullif(supplier_key,'')) suppliers,
                 quantile_cont(award_value,.25) FILTER(WHERE award_value>1) p25_value,median(award_value) FILTER(WHERE award_value>1) median_value,quantile_cont(award_value,.75) FILTER(WHERE award_value>1) p75_value,
                 sum(desk_analysis::int) desk_analysis_hits,sum(interview_consult::int) interview_hits,sum(survey_work::int) survey_hits,sum(workshop_focus::int) workshop_hits,sum(stakeholder_engagement::int) engagement_hits,sum(field_physical::int) field_hits,sum(report_deliverable::int) report_hits,sum(method_framework::int) method_hits,sum(specialist_credential::int) credential_hits
          FROM z GROUP BY 1,2,3),
      s0 AS (SELECT review_family,delivery_bundle,currency,supplier_key,count(*) n FROM z WHERE supplier_key<>'' GROUP BY 1,2,3,4),
      s AS (SELECT review_family,delivery_bundle,currency,max(n)*1.0/sum(n) top_supplier_share FROM s0 GROUP BY 1,2,3)
      SELECT b.*,s.top_supplier_share FROM b LEFT JOIN s USING(review_family,delivery_bundle,currency) ORDER BY review_family,awards DESC
    """).fetchall()
    write(out/'deliverable_matrix.csv',['review_family','delivery_bundle','currency','awards','buyers','suppliers','p25_value','median_value','p75_value','desk_analysis_hits','interview_hits','survey_hits','workshop_hits','engagement_hits','field_hits','report_hits','method_hits','credential_hits','top_supplier_share'],matrix)
    components=con.execute("""SELECT review_family,count(*) awards,sum(desk_analysis::int) desk_analysis,sum(interview_consult::int) interviews,sum(survey_work::int) surveys,sum(workshop_focus::int) workshops,sum(stakeholder_engagement::int) engagement,sum(field_physical::int) field_physical,sum(report_deliverable::int) reports,sum(method_framework::int) methods,sum(specialist_credential::int) credentials FROM z GROUP BY 1 ORDER BY awards DESC""").fetchall()
    write(out/'component_prevalence.csv',['review_family','awards','desk_analysis','interviews','surveys','workshops','engagement','field_physical','reports','methods','credentials'],components)
    suppliers=con.execute("""
      WITH s AS (SELECT review_family,delivery_bundle,supplier_key,any_value(supplier) supplier,count(*) awards,count(distinct nullif(buyer,'')) buyers,median(award_value) FILTER(WHERE award_value>1) median_award FROM z WHERE supplier_key<>'' GROUP BY 1,2,3)
      SELECT * FROM s QUALIFY row_number() over(partition by review_family,delivery_bundle order by buyers desc,awards desc,supplier)<=50 ORDER BY review_family,delivery_bundle,buyers DESC,awards DESC
    """).fetchall()
    write(out/'repeat_suppliers.csv',['review_family','delivery_bundle','supplier_key','supplier','awards','buyers','median_award'],suppliers)
    examples=con.execute("""SELECT review_family,delivery_bundle,tender_id,buyer,supplier,title,substr(description,1,1800) description_excerpt,award_value,desk_analysis,interview_consult,survey_work,workshop_focus,stakeholder_engagement,field_physical,report_deliverable,method_framework,specialist_credential FROM z QUALIFY row_number() over(partition by review_family,delivery_bundle order by award_value desc nulls last,tender_id)<=25 ORDER BY review_family,delivery_bundle,award_value DESC NULLS LAST""").fetchall()
    write(out/'examples.csv',['review_family','delivery_bundle','tender_id','buyer','supplier','title','description_excerpt','award_value','desk_analysis','interview_consult','survey_work','workshop_focus','stakeholder_engagement','field_physical','report_deliverable','method_framework','specialist_credential'],examples)
    summary={'version':'HISTORICAL_AU_REVIEW_DELIVERABLE_DECOMPOSITION_V1','archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'target_review_rows':con.execute('select count(*) from z').fetchone()[0],'delivery_bundles':dict(con.execute('select delivery_bundle,count(*) from z group by 1 order by 2 desc').fetchall()),'families':dict(con.execute('select review_family,count(*) from z group by 1 order by 2 desc').fetchall()),'historical_only':True,'record_deletion':False,'warning':'Component flags are semantic evidence, not proof that unmentioned activities were absent. DESK_ANALYTICAL_DOMINANT_PLAUSIBLE means no explicit human/field/credential cue was found in available title+description.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Australia Review Deliverable Decomposition v1','',f"- AusTender rows scanned **{summary['archive_records_scanned']:,}**",f"- target review/evaluation rows **{summary['target_review_rows']:,}**",'', 'A missing cue is never interpreted as proof of absence; this is a semantic decomposition of available descriptions.','']
    for row in matrix:
        fam,bundle,cur,n,buy,sup,p25,med,p75,*rest=row;share=rest[-1]
        lines += [f'## {fam} → {bundle}',f'- awards **{n}** · buyers **{buy}** · suppliers **{sup}** · p25/median/p75 **{p25}/{med}/{p75} {cur}** · top supplier **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
