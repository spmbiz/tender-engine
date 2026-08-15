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
      CREATE TABLE hh AS SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,
      Buyer_Name buyer,Title title,Scope_Summary scope_summary,Procedure procedure_text,coalesce(Main_CPV,'') main_cpv,
      coalesce(Raw_CPV_Description,'') cpv_description,try_cast(Official_Estimated_Value as double) estimated_value,
      lower(coalesce(Title,'')) title_l,lower(coalesce(Scope_Summary,'')) scope_l,
      lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''))) txt FROM {h}
    """)
    con.execute("""
      CREATE TABLE c0 AS SELECT *,CASE
      WHEN regexp_matches(title_l,'(?i)(rapid scientific evidence review|rapid evidence review|systematic review|evidence synthesis|rapid evidence assessment|literature review|revue de litt[ée]rature|revue documentaire|evidenzsynthese|literaturreview)') THEN 'EVIDENCE_LITERATURE_SYNTHESIS'
      WHEN regexp_matches(title_l,'(?i)(desk research|desktop research|documentary research|secondary research|benchmarking study|benchmark study|market intelligence research|étude.*desk research|studie.*desk research)') THEN 'DESK_RESEARCH_BENCHMARKING'
      WHEN regexp_matches(title_l,'(?i)(data capture services?|data entry services?|data keying|manual data entry|saisie de donn[ée]es|saisie.*donn[ée]es|dateneingabe|gegevensinvoer|dataregistratie)') THEN 'DATA_ENTRY_KEYING'
      WHEN regexp_matches(title_l,'(?i)(data collection services?|research data collection|survey data collection|datenerfassungs.*recherchedienstleistungen|collecte de donn[ée]es.*recherche|gegevensverzameling.*onderzoek)') THEN 'DATA_COLLECTION_RESEARCH'
      WHEN regexp_matches(title_l,'(?i)(data cleaning|data cleansing|data enrichment|data deduplication|data de-duplication|master data management|\bmdm\b|data quality remediation|datenbereinigung|nettoyage de donn[ée]es|opschonen van gegevens)') THEN 'DATA_CLEANING_ENRICHMENT_MDM'
      WHEN regexp_matches(title_l,'(?i)(collection,? codification,? validation|data validation service|data verification service|record validation|validation of records|coding and validation|codification.*records|validation.*statistical records|validation.*donn[ée]es)') THEN 'DATA_VALIDATION_CODING'
      WHEN regexp_matches(title_l,'(?i)(metadata creation|metadata enrichment|metadata management|metadata tagging|bibliographic metadata|bibliographic records|cataloguing services|cataloging services|katalogisierung|catalogisering|catalogage documentaire|indexing services|document indexing|indexation documentaire)') THEN 'METADATA_CATALOGUING_INDEXING'
      WHEN regexp_matches(title_l,'(?i)(ocr services?|optical character recognition|ocr extraction|text extraction.*documents?|document.*text extraction|reconnaissance optique de caract[èe]res|texterkennung)') THEN 'OCR_TEXT_EXTRACTION'
      WHEN regexp_matches(title_l,'(?i)(document scanning services?|scanning and indexing services?|archive digitisation services?|archive digitization services?|digitisation of archives|digitization of archives|num[ée]risation des archives|num[ée]risation de documents|digitalisierung von archiv|digitalisierung von dokument|digitalisering van archief|digitalisering van documenten)') THEN 'DOCUMENT_DIGITIZATION_SERVICES'
      WHEN regexp_matches(title_l,'(?i)(content migration services?|data migration services?|document migration services?|records migration|migration de donn[ée]es|datenmigration|gegevensmigratie|migration.*\bdata\b|\bdata\b.*migration)') THEN 'CONTENT_DATA_MIGRATION'
      WHEN regexp_matches(title_l,'(?i)(document conversion services?|data conversion services?|file format conversion|document format conversion|conversion de documents|xml conversion|pdf conversion|datenkonvertierung|documentconversie)') THEN 'DOCUMENT_DATA_CONVERSION'
      WHEN regexp_matches(title_l,'(?i)(document redaction services?|redaction services|document anonymi[sz]ation|anonymi[sz]ation of documents|caviardage de documents|anonymisation de documents|schw[äa]rzung.*dokument|documentanonimisering)') THEN 'DOCUMENT_REDACTION_ANONYMIZATION'
      WHEN regexp_matches(title_l,'(?i)(data annotation services?|data labelling services?|data labeling services?|image annotation services?|text annotation services?|training data annotation|ground truth annotation|annotation de donn[ée]es|datenannotation)') THEN 'DATA_ANNOTATION_LABELING'
      WHEN regexp_matches(title_l,'(?i)(survey coding|questionnaire coding|open[- ]ended response coding|survey tabulation|survey data processing|survey data cleaning|codification.*questionnaire)') THEN 'SURVEY_DATA_PROCESSING'
      WHEN regexp_matches(title_l,'(?i)(database maintenance services?|database updating services?|database population services?|registry maintenance services?|register maintenance services?|maintenance (du |d.un )?\bregistre\b|mise [àa] jour.*\bbase de donn[ée]es\b|maintenance.*\bbase de donn[ée]es\b|aktualisierung.*datenbank|datenbankpflege|databasebeheer|databankonderhoud)') THEN 'DATABASE_REGISTRY_OPERATIONS'
      WHEN regexp_matches(title_l,'(?i)(knowledge base maintenance|knowledge base content|knowledge capture services?|knowledge management services?|gestion.*base de connaissances)') THEN 'KNOWLEDGE_CONTENT_OPERATIONS'
      ELSE NULL END info_family FROM hh
    """)
    con.execute("""
      CREATE TABLE c AS SELECT *,CASE
      WHEN info_family IS NULL THEN NULL
      WHEN info_family='DOCUMENT_DIGITIZATION_SERVICES' THEN 'PHYSICAL_DOCUMENT_INPUT'
      WHEN info_family='DATA_ENTRY_KEYING' AND regexp_matches(title_l,'(?i)(inspection|inventor(y|ie)|building survey|site survey|terrain|field|school|école|établissement|asset inventory)') THEN 'PHYSICAL_COLLECTION_PLUS_ENTRY'
      WHEN info_family='DATA_ENTRY_KEYING' AND regexp_matches(title_l,'(?i)(interface|software|hardware|application|system|système|lösung|solution|tool)') THEN 'PLATFORM_OR_IMPLEMENTATION'
      WHEN info_family='DATA_COLLECTION_RESEARCH' AND regexp_matches(txt,'(?i)(traffic count|traffic data|fieldwork|field work|in[- ]person|on[- ]site|onsite|site visit|focus groups?|face[- ]to[- ]face|physical sampling)') THEN 'HUMAN_OR_LOCATION_HEAVY'
      WHEN info_family='DATA_VALIDATION_CODING' AND regexp_matches(txt,'(?i)(terrain|field validation|site visit|inspection|physical verification)') THEN 'HUMAN_OR_LOCATION_HEAVY'
      WHEN info_family='CONTENT_DATA_MIGRATION' AND NOT regexp_matches(title_l,'(?i)(\bdata\b|donn[ée]es|daten|gegevens|document|records?|content|database|application)') THEN 'SEMANTIC_COLLISION_PRESERVED'
      WHEN info_family='CONTENT_DATA_MIGRATION' AND regexp_matches(title_l,'(?i)(sap|s/4hana|erp|hospital information system|\bkis\b|software|platform|system|système|infrastructure|implementation|implementierung|impl[ée]mentation|refonte|replacement|remplacement|transformation)') THEN 'EMBEDDED_COMPLEX_IT'
      WHEN info_family='DATA_CLEANING_ENRICHMENT_MDM' AND regexp_matches(title_l,'(?i)(platform|software|tool|solution|implementation|implementierung|impl[ée]mentation|licen[cs]e|cloud|azure|sas |system|système|ratkaisu)') THEN 'PLATFORM_OR_IMPLEMENTATION'
      WHEN info_family='OCR_TEXT_EXTRACTION' AND regexp_matches(title_l,'(?i)(acquisition|acquire|purchase|procurement|software|solution|licen[cs]e|subscription|abonnement|abo|tool|system|système|beschaffung|erwerb)') THEN 'PLATFORM_OR_SOFTWARE'
      WHEN info_family='OCR_TEXT_EXTRACTION' AND regexp_matches(title_l,'(?i)(microfilm|historical|archive|archiv|digitization|digitisation|digitalisierung|num[ée]risation|scanning)') THEN 'PHYSICAL_DOCUMENT_INPUT'
      WHEN info_family='DATABASE_REGISTRY_OPERATIONS' AND regexp_matches(title_l,'(?i)(software|platform|system|application|implementation|hosting|outil|lösung|solution)') THEN 'PLATFORM_OR_IMPLEMENTATION'
      WHEN info_family='EVIDENCE_LITERATURE_SYNTHESIS' AND regexp_matches(txt,'(?i)(phd|doctorate|engineer|engineering|medical|clinical|licensed|licenced|registered professional|specialist qualification|fisheries ecology|biological field)') THEN 'DOMAIN_SPECIALIST_REVIEW'
      WHEN regexp_matches(title_l,'(?i)(on[- ]?site|sur site|vor ort|ter plaatse|field work|fieldwork|in[- ]person)') THEN 'HUMAN_OR_LOCATION_HEAVY'
      ELSE 'PURE_DIGITAL_OR_REMOTE_SERVICE' END purity_class FROM c0 WHERE info_family IS NOT NULL
    """)
    con.execute(f"CREATE TABLE astat AS SELECT Historical_Tender_ID tender_id,median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>=0) award_value,median(try_cast(Bidder_Count as double)) FILTER(WHERE try_cast(Bidder_Count as double)>=0) bidder_count FROM {aw} GROUP BY 1")
    con.execute(f"""CREATE TABLE ts AS WITH b0 AS (SELECT Award_ID award_id,coalesce(nullif(Supplier_ID,''),nullif(Supplier_Name,''),'UNKNOWN_SUPPLIER') sid,coalesce(nullif(Supplier_Name,''),nullif(Supplier_ID,''),'UNKNOWN_SUPPLIER') sname FROM {br}),bn AS (SELECT *,count(*) over(partition by award_id) n FROM b0),aa AS (SELECT Award_ID award_id,Historical_Tender_ID tender_id FROM {aw}) SELECT aa.tender_id,bn.sid,bn.sname,1.0/nullif(bn.n,0) w FROM aa JOIN bn USING(award_id)""")
    con.execute("CREATE TABLE p AS SELECT c.*,coalesce(a.award_value,c.estimated_value) reference_value,a.bidder_count FROM c LEFT JOIN astat a USING(tender_id)")
    con.execute("CREATE TABLE bs AS SELECT info_family,purity_class,country,currency,buyer,count(*) n FROM p WHERE buyer<>'' GROUP BY 1,2,3,4,5")
    con.execute("CREATE TABLE ss AS SELECT p.info_family,p.purity_class,p.country,p.currency,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4,5")
    matrix=con.execute("""WITH b AS (SELECT info_family,purity_class,country,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,quantile_cont(reference_value,.25) FILTER(WHERE reference_value>=0) p25_value,median(reference_value) FILTER(WHERE reference_value>=0) median_value,quantile_cont(reference_value,.75) FILTER(WHERE reference_value>=0) p75_value,median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders FROM p GROUP BY 1,2,3,4),rb AS (SELECT info_family,purity_class,country,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM bs GROUP BY 1,2,3,4),sx AS (SELECT info_family,purity_class,country,currency,count(*) suppliers,max(n)/nullif(sum(n),0) top_supplier_share FROM ss GROUP BY 1,2,3,4) SELECT b.*,coalesce(rb.repeat_buyers,0),sx.suppliers,sx.top_supplier_share FROM b LEFT JOIN rb USING(info_family,purity_class,country,currency) LEFT JOIN sx USING(info_family,purity_class,country,currency) ORDER BY purity_class,records DESC,buyers DESC""").fetchall()
    write(out/'market_matrix.csv',['info_family','purity_class','country','currency','records','buyers','p25_value','median_value','p75_value','median_bidders','repeat_buyers','suppliers','top_supplier_share'],matrix)
    fam=con.execute("""WITH b AS (SELECT info_family,purity_class,count(*) records,count(distinct nullif(buyer,'')) buyers,median(reference_value) FILTER(WHERE reference_value>=0) median_value,median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders FROM p GROUP BY 1,2),s0 AS (SELECT info_family,purity_class,sid,sum(n) n FROM ss GROUP BY 1,2,3),s AS (SELECT info_family,purity_class,count(*) suppliers,max(n)/nullif(sum(n),0) top_supplier_share FROM s0 GROUP BY 1,2) SELECT b.*,s.suppliers,s.top_supplier_share FROM b LEFT JOIN s USING(info_family,purity_class) ORDER BY CASE WHEN purity_class='PURE_DIGITAL_OR_REMOTE_SERVICE' THEN 0 ELSE 1 END,records DESC""").fetchall()
    write(out/'family_purity_summary.csv',['info_family','purity_class','records','buyers','median_value','median_bidders','suppliers','top_supplier_share'],fam)
    examples=con.execute("""SELECT info_family,purity_class,country,currency,tender_id,buyer,title,substr(scope_summary,1,1800) scope_excerpt,main_cpv,cpv_description,reference_value,bidder_count,procedure_text FROM p QUALIFY row_number() over(partition by info_family,purity_class,country,currency order by reference_value desc nulls last,tender_id)<=20 ORDER BY info_family,purity_class,country,reference_value DESC NULLS LAST""").fetchall()
    write(out/'examples.csv',['info_family','purity_class','country','currency','tender_id','buyer','title','scope_excerpt','main_cpv','cpv_description','reference_value','bidder_count','procedure'],examples)
    pure=con.execute("""SELECT info_family,count(*) records,count(distinct nullif(buyer,'')) buyers,count(distinct country) countries,median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders FROM p WHERE purity_class='PURE_DIGITAL_OR_REMOTE_SERVICE' GROUP BY 1 ORDER BY records DESC""").fetchall()
    write(out/'pure_core.csv',['info_family','records','buyers','countries','median_bidders'],pure)
    summary={'version':'HISTORICAL_INFORMATION_WORK_PURE_CORE_V3_1','archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'strict_title_matches':con.execute('select count(*) from p').fetchone()[0],'pure_digital_remote_rows':con.execute("select count(*) from p where purity_class='PURE_DIGITAL_OR_REMOTE_SERVICE'").fetchone()[0],'purity_classes':dict(con.execute('select purity_class,count(*) from p group by 1 order by 2 desc').fetchall()),'pure_families':dict(con.execute("select info_family,count(*) from p where purity_class='PURE_DIGITAL_OR_REMOTE_SERVICE' group by 1 order by 2 desc").fetchall()),'grain':'NOTICE_FIRST_TENDER','historical_only':True,'record_deletion':False,'live_used':False,'dce_used':False,'supersession':'v3.0 pure-core routing is superseded by v3.1 after semantic QA found registre/enregistrement, inspection+entry and OCR-software collisions. Underlying source records remain preserved.','warning':'Purity is a semantic routing heuristic; examples still require QA before strategic promotion.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Historical Information-Work Pure Core v3.1','',f"- Global Core records scanned **{summary['archive_records_scanned']:,}**",f"- strict title-led matches **{summary['strict_title_matches']:,}**",f"- pure digital/remote-service rows **{summary['pure_digital_remote_rows']:,}**",'', 'v3.1 separates pure digital services from embedded IT, OCR software procurement, physical document input, inspection+entry, specialist review and semantic collisions. Source records are never deleted.','']
    for family,n,buy,countries,bidders in pure:lines += [f'## {family}',f'- pure rows **{n}** · buyers **{buy}** · countries **{countries}** · median bidders **{bidders if bidders is not None else "UNKNOWN"}**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
