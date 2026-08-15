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
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--bridge',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute('SET threads=4');con.execute("SET memory_limit='5GB'")
    h=f"read_parquet('{a.historical}')";aw=f"read_parquet('{a.awards}')";br=f"read_parquet('{a.bridge}')"
    con.execute(f"""
      CREATE TABLE hh AS
      SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,
             Buyer_Name buyer,Title title,Scope_Summary scope_summary,Procedure procedure_text,
             coalesce(Main_CPV,'') main_cpv,coalesce(Raw_CPV_Description,'') cpv_description,
             try_cast(Official_Estimated_Value as double) estimated_value,
             lower(coalesce(Title,'')) title_l,
             lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''))) txt
      FROM {h}
    """)
    # Family order matters: precise specialized workflows before broad research/records terms.
    con.execute("""
      CREATE TABLE c0 AS SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(data (entry|capture|keying|input)|saisie de donn[ée]es|datenerfassung|gegevensinvoer|dataregistratie)') THEN 'DATA_ENTRY_CAPTURE'
        WHEN regexp_matches(txt,'(?i)(data (cleaning|cleansing|normalisation|normalization|deduplication|de-duplication|enrichment)|nettoyage de donn[ée]es|quality.*data|data quality remediation|gegevenskwaliteit|datenbereinigung)') THEN 'DATA_CLEANING_ENRICHMENT'
        WHEN regexp_matches(txt,'(?i)(data (validation|verification)|validate.*data|v[ée]rification.*donn[ée]es|data quality assurance|record validation|gegevensvalidatie|datenvalidierung)') THEN 'DATA_VALIDATION_QA'
        WHEN regexp_matches(txt,'(?i)(data annotation|data labelling|data labeling|image annotation|text annotation|training data|ground truth|human annotation)') THEN 'DATA_ANNOTATION_LABELING'
        WHEN regexp_matches(txt,'(?i)(catalogu(e|ing|ing services)|cataloguing|cataloging|metadata creation|metadata enrichment|metadata management|indexing services|indexation|bibliographic records|bibliographic metadata|metadata tagging)') THEN 'CATALOGUING_METADATA_INDEXING'
        WHEN regexp_matches(txt,'(?i)(records management|record management services|document records management|archive management|archival services|archiving services|gestion des archives|gestion documentaire|aktenmanagement|archiefbeheer)') THEN 'RECORDS_ARCHIVE_MANAGEMENT'
        WHEN regexp_matches(txt,'(?i)(document scanning|scanning services|digitisation services|digitization services|digitalisation of archives|digitalization of archives|num[ée]risation|scanning and indexing|scan.*archive|ocr services|optical character recognition)') THEN 'DIGITIZATION_SCANNING_OCR'
        WHEN regexp_matches(txt,'(?i)(document conversion|file format conversion|format conversion|conversion of documents|conversion de documents|document transformation|pdf conversion|xml conversion|data conversion services)') THEN 'DOCUMENT_DATA_CONVERSION'
        WHEN regexp_matches(txt,'(?i)(content migration|data migration services|document migration|records migration|migration of content|migration of data|migration de donn[ée]es|datenmigration|gegevensmigratie)') THEN 'CONTENT_DATA_MIGRATION'
        WHEN regexp_matches(txt,'(?i)(content management services|content maintenance|website content migration|digital content management|knowledge base maintenance|content population|content upload|content entry)') THEN 'CONTENT_OPERATIONS'
        WHEN regexp_matches(txt,'(?i)(knowledge management services|knowledge base|knowledge management system|knowledge capture|knowledge transfer service)') THEN 'KNOWLEDGE_MANAGEMENT'
        WHEN regexp_matches(txt,'(?i)(document redaction|redaction services|document review.*redact|information redaction|caviardage|anonymi[sz]ation of documents|document anonymi[sz]ation)') THEN 'DOCUMENT_REDACTION_ANONYMIZATION'
        WHEN regexp_matches(txt,'(?i)(e-discovery|ediscovery|electronic discovery|legal document review|disclosure review|document disclosure services|litigation document review)') THEN 'E_DISCOVERY_DOCUMENT_REVIEW'
        WHEN regexp_matches(txt,'(?i)(literature review|systematic review|evidence review|evidence synthesis|rapid evidence assessment|research synthesis|desk research|documentary research|revue de litt[ée]rature|revue documentaire)') THEN 'EVIDENCE_RESEARCH_SYNTHESIS'
        WHEN regexp_matches(txt,'(?i)(market research|market study|market analysis|benchmarking study|benchmark study|desk study|research services|research study|policy research|policy analysis|economic research)') THEN 'RESEARCH_ANALYSIS'
        WHEN regexp_matches(txt,'(?i)(survey data processing|survey coding|questionnaire coding|survey tabulation|survey data cleaning|survey data analysis|coding of responses|open[- ]ended coding)') THEN 'SURVEY_DATA_PROCESSING'
        WHEN regexp_matches(txt,'(?i)(database maintenance|database updating|database population|database creation|registry maintenance|register maintenance|data repository maintenance)') THEN 'DATABASE_REGISTRY_OPERATIONS'
        WHEN regexp_matches(txt,'(?i)(information retrieval services|document retrieval|research and retrieval|information search services|database search services)') THEN 'INFORMATION_RETRIEVAL'
        ELSE NULL END info_family
      FROM hh
    """)
    # Remove obvious semantic collisions while preserving excluded records in the canonical archive.
    con.execute("""
      CREATE TABLE c AS SELECT *,CASE
        WHEN info_family IS NULL THEN NULL
        WHEN regexp_matches(txt,'(?i)(construction records|medical records software|electronic health record system|criminal records check|background check|vinyl record|music records|record player|sports record|temperature record|recording studio|audio recording services)') THEN 'SEMANTIC_COLLISION_RISK'
        WHEN regexp_matches(txt,'(?i)(physical storage|offsite storage|box storage|archive storage|warehouse|warehousing|transport.*archives|collection.*archives|paper archives|hard copy|physical files|microfilm|microfiche)') THEN 'PHYSICAL_INPUT_OR_STORAGE'
        WHEN regexp_matches(txt,'(?i)(onsite|on-site|on site|at the premises|sur site)') THEN 'ONSITE_OR_LOCATION_DEPENDENT'
        WHEN info_family IN ('E_DISCOVERY_DOCUMENT_REVIEW') THEN 'LEGAL_SPECIALIST_RISK'
        WHEN info_family='DIGITIZATION_SCANNING_OCR' AND regexp_matches(txt,'(?i)(books|files|paper|archives|documents|microfilm|microfiche)') THEN 'PHYSICAL_INPUT_OR_STORAGE'
        ELSE 'DIGITAL_FIRST_OR_REMOTE_PLAUSIBLE' END delivery_flag,
        CASE WHEN info_family IS NOT NULL AND regexp_matches(title_l,'(?i)(data|donn[ée]es|metadata|catalog|index|records|archive|digit|scan|ocr|conversion|migration|content|knowledge|redaction|anonym|e-discovery|ediscovery|literature|evidence|research|survey|database|registry|information retrieval)') THEN 'TITLE_SIGNAL' WHEN info_family IS NOT NULL THEN 'SCOPE_ONLY_SIGNAL' ELSE NULL END signal_source
      FROM c0 WHERE info_family IS NOT NULL
    """)
    con.execute(f"""
      CREATE TABLE astat AS
      SELECT Historical_Tender_ID tender_id,
             median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>=0) award_value,
             median(try_cast(Bidder_Count as double)) FILTER(WHERE try_cast(Bidder_Count as double)>=0) bidder_count
      FROM {aw} GROUP BY 1
    """)
    con.execute(f"""
      CREATE TABLE ts AS
      WITH b0 AS (
        SELECT Award_ID award_id,coalesce(nullif(Supplier_ID,''),nullif(Supplier_Name,''),'UNKNOWN_SUPPLIER') sid,
               coalesce(nullif(Supplier_Name,''),nullif(Supplier_ID,''),'UNKNOWN_SUPPLIER') sname
        FROM {br}
      ), bn AS (SELECT *,count(*) over(partition by award_id) n FROM b0), aa AS (SELECT Award_ID award_id,Historical_Tender_ID tender_id FROM {aw})
      SELECT aa.tender_id,bn.sid,bn.sname,1.0/nullif(bn.n,0) w FROM aa JOIN bn USING(award_id)
    """)
    con.execute("CREATE TABLE p AS SELECT c.*,coalesce(a.award_value,c.estimated_value) reference_value,a.bidder_count FROM c LEFT JOIN astat a USING(tender_id) WHERE delivery_flag<>'SEMANTIC_COLLISION_RISK'")
    con.execute("CREATE TABLE bs0 AS SELECT info_family,delivery_flag,signal_source,country,currency,buyer,count(*) n FROM p WHERE buyer<>'' GROUP BY 1,2,3,4,5,6")
    con.execute("CREATE TABLE ss0 AS SELECT p.info_family,p.delivery_flag,p.signal_source,p.country,p.currency,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4,5,6")
    matrix=con.execute("""
      WITH b AS (
        SELECT info_family,delivery_flag,signal_source,country,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,
               quantile_cont(reference_value,.25) FILTER(WHERE reference_value>=0) p25_value,
               median(reference_value) FILTER(WHERE reference_value>=0) median_value,
               quantile_cont(reference_value,.75) FILTER(WHERE reference_value>=0) p75_value,
               median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders
        FROM p GROUP BY 1,2,3,4,5
      ), rb AS (SELECT info_family,delivery_flag,signal_source,country,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM bs0 GROUP BY 1,2,3,4,5),
      ss AS (SELECT info_family,delivery_flag,signal_source,country,currency,count(*) suppliers,sum(n) linked_weight,max(n)/nullif(sum(n),0) top_supplier_share FROM ss0 GROUP BY 1,2,3,4,5)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.suppliers,ss.linked_weight,ss.top_supplier_share
      FROM b LEFT JOIN rb USING(info_family,delivery_flag,signal_source,country,currency)
      LEFT JOIN ss USING(info_family,delivery_flag,signal_source,country,currency)
      ORDER BY records DESC,buyers DESC
    """).fetchall()
    write(out/'market_matrix.csv',['info_family','delivery_flag','signal_source','country','currency','records','buyers','p25_value','median_value','p75_value','median_bidders','repeat_buyers','suppliers','linked_weight','top_supplier_share'],matrix)
    fam=con.execute("""
      WITH b AS (SELECT info_family,count(*) records,count(distinct nullif(buyer,'')) buyers,median(reference_value) FILTER(WHERE reference_value>=0) median_value,median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders FROM p GROUP BY 1),
      ss0 AS (SELECT info_family,sid,sum(n) n FROM ss0 GROUP BY 1,2),ss AS (SELECT info_family,count(*) suppliers,max(n)/nullif(sum(n),0) top_supplier_share FROM ss0 GROUP BY 1)
      SELECT b.*,ss.suppliers,ss.top_supplier_share FROM b LEFT JOIN ss USING(info_family) ORDER BY records DESC
    """).fetchall();write(out/'family_summary.csv',['info_family','records','buyers','median_value','median_bidders','suppliers','top_supplier_share'],fam)
    winners=con.execute("""
      SELECT info_family,country,currency,supplier,n,n/nullif(sum(n) over(partition by info_family,country,currency),0) supplier_share FROM ss0
      QUALIFY row_number() over(partition by info_family,country,currency order by n desc,supplier)<=15 ORDER BY info_family,country,currency,n DESC
    """).fetchall();write(out/'top_winners.csv',['info_family','country','currency','supplier','weighted_awards','supplier_share'],winners)
    buyers=con.execute("""
      SELECT info_family,country,currency,buyer,count(*) records FROM p WHERE buyer<>'' GROUP BY 1,2,3,4
      QUALIFY row_number() over(partition by info_family,country,currency order by count(*) desc,buyer)<=15 ORDER BY info_family,country,currency,records DESC
    """).fetchall();write(out/'top_buyers.csv',['info_family','country','currency','buyer','records'],buyers)
    examples=con.execute("""
      SELECT info_family,delivery_flag,signal_source,country,currency,tender_id,buyer,title,substr(scope_summary,1,1400) scope_excerpt,main_cpv,cpv_description,reference_value,bidder_count,procedure_text FROM p
      QUALIFY row_number() over(partition by info_family,delivery_flag,signal_source,country,currency order by reference_value desc nulls last,tender_id)<=12
      ORDER BY info_family,country,currency,reference_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['info_family','delivery_flag','signal_source','country','currency','tender_id','buyer','title','scope_excerpt','main_cpv','cpv_description','reference_value','bidder_count','procedure'],examples)
    collisions=con.execute("""SELECT info_family,count(*) records FROM c WHERE delivery_flag='SEMANTIC_COLLISION_RISK' GROUP BY 1 ORDER BY 2 DESC""").fetchall();write(out/'semantic_collisions_preserved.csv',['info_family','records_preserved_for_reclassification'],collisions)
    summary={'version':'HISTORICAL_INFORMATION_WORK_PRECISION_V1','archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'broad_matches_including_collisions':con.execute('select count(*) from c').fetchone()[0],'precision_rows':con.execute('select count(*) from p').fetchone()[0],'families':dict(con.execute('select info_family,count(*) from p group by 1 order by 2 desc').fetchall()),'delivery_flags':dict(con.execute('select delivery_flag,count(*) from p group by 1 order by 2 desc').fetchall()),'signal_sources':dict(con.execute('select signal_source,count(*) from p group by 1 order by 2 desc').fetchall()),'semantic_collision_rows_preserved':con.execute("select count(*) from c where delivery_flag='SEMANTIC_COLLISION_RISK'").fetchone()[0],'grain':'NOTICE_FIRST_TENDER','historical_only':True,'live_used':False,'dce_used':False,'record_deletion':False,'interpretation':'Discovery/market-structure layer. Semantic QA required before Atlas promotion.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Historical Information-Work Precision v1','',f"- Global Core notice-first records scanned: **{summary['archive_records_scanned']:,}**",f"- broad information-work matches incl. preserved collisions: **{summary['broad_matches_including_collisions']:,}**",f"- precision review rows: **{summary['precision_rows']:,}**",f"- semantic-collision rows preserved for reclassification: **{summary['semantic_collision_rows_preserved']:,}**",'', 'This is historical-only discovery. `delivery_flag` is a triage characteristic, not an eligibility verdict. Scope-only matches remain visible instead of being silently discarded.','']
    for r in fam:
        family,n,buy,med,bid,sup,share=r;lines += [f'## {family}',f'- records **{n}** · buyers **{buy}** · median **{med if med is not None else "UNKNOWN"}** · median bidders **{bid if bid is not None else "UNKNOWN"}** · suppliers **{sup if sup is not None else "UNKNOWN"}** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
