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
    h=f"read_csv_auto('{a.historical}',header=true,all_varchar=true,sample_size=200000,compression='auto')"
    aw=f"read_csv_auto('{a.awards}',header=true,all_varchar=true,sample_size=200000,compression='auto')"
    con.execute(f"""
      CREATE TABLE x0 AS
      WITH hh AS (
        SELECT Historical_Tender_ID tender_id,Buyer_Name buyer,Title title,coalesce(Description,'') description,
               coalesce(Subcategory,'') subcategory,coalesce(Category,'') category,
               lower(concat_ws(' ',coalesce(Title,''),coalesce(Description,''),coalesce(Subcategory,''),coalesce(Category,''))) txt
        FROM {h}
      ), aa AS (
        SELECT Historical_Tender_ID tender_id,Supplier_Name supplier,try_cast(Award_Value as double) award_value,
               upper(coalesce(nullif(Currency,''),'AUD')) currency
        FROM {aw}
      ) SELECT hh.*,aa.supplier,aa.award_value,aa.currency FROM hh LEFT JOIN aa USING(tender_id)
    """)
    # supplier_key is intentionally heuristic and preserved alongside raw supplier names.
    con.execute("""
      CREATE TABLE x AS SELECT *,
        CASE WHEN coalesce(supplier,'')='' THEN '' ELSE
          regexp_replace(
            regexp_replace(upper(coalesce(supplier,'')),'[^A-Z0-9]','','g'),
            '(PTYLIMITED|PTYLTD|PROPRIETARYLIMITED|LIMITED|LTD|INCORPORATED|LLC)$',''
          ) END supplier_key
      FROM x0
    """)
    con.execute("""
      CREATE TABLE c0 AS SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(recruitment|recruiting|personnel recruitment|executive search|headhunt|talent acquisition|candidate search|recruitment process outsourcing|\brpo\b)') THEN 'RECRUITMENT_MATCHING'
        WHEN regexp_matches(txt,'(?i)(training|education and training|learning service|courseware|e-learning|elearning|learning management|training material|training design|training development|instructional design|facilitat|workshop|coaching|tuition|course delivery)') THEN 'TRAINING_EDUCATION'
        WHEN regexp_matches(txt,'(?i)(assurance review|independent review|gateway review|health check review|quality review|evaluation service|program evaluation|programme evaluation|independent assessment|specialist review)') THEN 'ASSURANCE_REVIEW_EVALUATION'
        WHEN regexp_matches(txt,'(?i)(event management|event services|conference management|conference services|venue hire|event production|conference production|exhibition management)') THEN 'EVENT_CONFERENCE'
        ELSE NULL END market_family FROM x
    """)
    con.execute("""
      CREATE TABLE y AS SELECT *,CASE
        WHEN market_family='RECRUITMENT_MATCHING' AND regexp_matches(txt,'(?i)(executive search|headhunt|senior executive|executive recruitment)') THEN 'EXECUTIVE_SEARCH'
        WHEN market_family='RECRUITMENT_MATCHING' AND regexp_matches(txt,'(?i)(psychometric|candidate assessment|assessment centre|assessment center|pre-employment|background screening|reference check)') THEN 'CANDIDATE_ASSESSMENT_SCREENING'
        WHEN market_family='RECRUITMENT_MATCHING' AND regexp_matches(txt,'(?i)(recruitment process outsourcing|\brpo\b)') THEN 'RPO'
        WHEN market_family='RECRUITMENT_MATCHING' AND regexp_matches(txt,'(?i)(temporary|labour hire|labor hire|contractor|contingent|casual staff|personnel hire)') THEN 'TEMP_CONTRACTOR_RECRUITMENT'
        WHEN market_family='RECRUITMENT_MATCHING' THEN 'GENERAL_RECRUITMENT_SEARCH'
        WHEN market_family='TRAINING_EDUCATION' AND regexp_matches(txt,'(?i)(e-learning|elearning|online learning|digital learning|courseware|learning management|\blms\b|virtual learning|web based training)') THEN 'DIGITAL_ELEARNING_PLATFORM_CONTENT'
        WHEN market_family='TRAINING_EDUCATION' AND regexp_matches(txt,'(?i)(instructional design|training design|training development|develop.*training|learning design|course development|curriculum development|training material)') THEN 'TRAINING_DESIGN_CONTENT'
        WHEN market_family='TRAINING_EDUCATION' AND regexp_matches(txt,'(?i)(tuition|university fees|course fees|educational service agreement|certification|accreditation exam|qualification)') THEN 'TUITION_CERTIFICATION'
        WHEN market_family='TRAINING_EDUCATION' AND regexp_matches(txt,'(?i)(coaching|leadership development|executive development|mentoring)') THEN 'COACHING_LEADERSHIP'
        WHEN market_family='TRAINING_EDUCATION' AND regexp_matches(txt,'(?i)(facilitat|workshop|trainer|training delivery|deliver.*training|instructor|classroom)') THEN 'INSTRUCTOR_FACILITATION'
        WHEN market_family='TRAINING_EDUCATION' THEN 'GENERAL_TRAINING_EDUCATION'
        WHEN market_family='ASSURANCE_REVIEW_EVALUATION' AND regexp_matches(txt,'(?i)(gateway review|assurance review|health check review)') THEN 'PROJECT_PROGRAM_ASSURANCE_REVIEW'
        WHEN market_family='ASSURANCE_REVIEW_EVALUATION' AND regexp_matches(txt,'(?i)(program evaluation|programme evaluation|evaluation service)') THEN 'PROGRAM_EVALUATION'
        WHEN market_family='ASSURANCE_REVIEW_EVALUATION' THEN 'INDEPENDENT_SPECIALIST_REVIEW'
        WHEN market_family='EVENT_CONFERENCE' AND regexp_matches(txt,'(?i)(venue hire|venue rental)') THEN 'VENUE_HIRE'
        WHEN market_family='EVENT_CONFERENCE' AND regexp_matches(txt,'(?i)(event management|conference management)') THEN 'EVENT_MANAGEMENT'
        WHEN market_family='EVENT_CONFERENCE' THEN 'EVENT_CONFERENCE_OTHER'
        ELSE NULL END subfamily FROM c0 WHERE market_family IS NOT NULL
    """)
    matrix=con.execute("""
      WITH b AS (
        SELECT market_family,subfamily,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,
               count(distinct nullif(supplier,'')) raw_suppliers,count(distinct nullif(supplier_key,'')) normalized_supplier_keys,
               quantile_cont(award_value,.25) FILTER(WHERE award_value>=0) p25_value,median(award_value) FILTER(WHERE award_value>=0) median_value,
               quantile_cont(award_value,.75) FILTER(WHERE award_value>=0) p75_value
        FROM y GROUP BY 1,2,3
      ), rb0 AS (SELECT market_family,subfamily,currency,buyer,count(*) n FROM y WHERE buyer<>'' GROUP BY 1,2,3,4),
      rb AS (SELECT market_family,subfamily,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM rb0 GROUP BY 1,2,3),
      sr AS (SELECT market_family,subfamily,currency,supplier,count(*) n FROM y WHERE supplier<>'' GROUP BY 1,2,3,4),
      sr2 AS (SELECT market_family,subfamily,currency,max(n)*1.0/sum(n) raw_top_supplier_share FROM sr GROUP BY 1,2,3),
      sn AS (SELECT market_family,subfamily,currency,supplier_key,count(*) n FROM y WHERE supplier_key<>'' GROUP BY 1,2,3,4),
      sn2 AS (SELECT market_family,subfamily,currency,max(n)*1.0/sum(n) normalized_top_supplier_share FROM sn GROUP BY 1,2,3)
      SELECT b.*,coalesce(rb.repeat_buyers,0),sr2.raw_top_supplier_share,sn2.normalized_top_supplier_share
      FROM b LEFT JOIN rb USING(market_family,subfamily,currency) LEFT JOIN sr2 USING(market_family,subfamily,currency) LEFT JOIN sn2 USING(market_family,subfamily,currency)
      ORDER BY market_family,records DESC
    """).fetchall()
    write(out/'market_matrix.csv',['family','subfamily','currency','records','buyers','raw_suppliers','normalized_supplier_keys','p25_value','median_value','p75_value','repeat_buyers','raw_top_supplier_share','normalized_top_supplier_share'],matrix)
    winners=con.execute("""
      SELECT market_family,subfamily,currency,supplier_key,any_value(supplier) representative_supplier,count(*) awards,
             count(*)*1.0/sum(count(*)) over(partition by market_family,subfamily,currency) normalized_supplier_share
      FROM y WHERE supplier_key<>'' GROUP BY 1,2,3,4
      QUALIFY row_number() over(partition by market_family,subfamily,currency order by count(*) desc,supplier_key)<=20
      ORDER BY market_family,subfamily,awards DESC
    """).fetchall();write(out/'top_winners_normalized.csv',['family','subfamily','currency','supplier_key','representative_supplier','awards','normalized_supplier_share'],winners)
    buyers=con.execute("""
      SELECT market_family,subfamily,currency,buyer,count(*) awards FROM y WHERE buyer<>'' GROUP BY 1,2,3,4
      QUALIFY row_number() over(partition by market_family,subfamily,currency order by count(*) desc,buyer)<=20
      ORDER BY market_family,subfamily,awards DESC
    """).fetchall();write(out/'top_buyers.csv',['family','subfamily','currency','buyer','awards'],buyers)
    examples=con.execute("""
      SELECT market_family,subfamily,currency,tender_id,buyer,supplier,title,substr(description,1,1200) description_excerpt,
             award_value,subcategory,category FROM y
      QUALIFY row_number() over(partition by market_family,subfamily,currency order by award_value desc nulls last,tender_id)<=15
      ORDER BY market_family,subfamily,award_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['family','subfamily','currency','tender_id','buyer','supplier','title','description_excerpt','award_value','subcategory','category'],examples)
    summary={'version':'HISTORICAL_AU_ASYMMETRIC_SERVICES_V2','archive_records_scanned':con.execute('select count(*) from x').fetchone()[0],'classified_rows':con.execute('select count(*) from y').fetchone()[0],'families':dict(con.execute('select market_family,count(*) from y group by 1 order by 2 desc').fetchall()),'grain':'AWARD_FIRST_PROCUREMENT','historical_only':True,'supplier_entity_resolution':'HEURISTIC_NAME_NORMALIZATION_ONLY','live_used':False,'dce_used':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Australia Asymmetric Services Decomposition v2','',f"- records scanned **{summary['archive_records_scanned']:,}** · classified **{summary['classified_rows']:,}**",'- v2 preserves description excerpts and reports raw plus heuristic-normalized supplier concentration.','- Supplier normalization is not legal-entity resolution; it only reduces obvious case/punctuation/legal-suffix aliases.','']
    for r in matrix:
      fam,sub,cur,n,buy,rs,ns,p25,med,p75,rb,rshare,nshare=r
      lines += [f'## {fam} → {sub}',f'- records **{n}** · buyers **{buy}** · repeat buyers **{rb}** · raw suppliers **{rs}** · normalized keys **{ns}**',f'- {cur} p25/median/p75 **{p25 if p25 is not None else "UNKNOWN"} / {med if med is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}**',f'- top supplier share raw **{round(100*rshare,1) if rshare is not None else "UNKNOWN"}%** · normalized **{round(100*nshare,1) if nshare is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
