#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json,math,re
from datetime import datetime,timezone
from pathlib import Path
import duckdb

VERSION='SPM_MARKET_INTELLIGENCE_V6_CLEAN'


def qi(s): return '"'+s.replace('"','""')+'"'
def choose(cols,*names):
    m={x.casefold():x for x in cols}
    for n in names:
        if n.casefold() in m:return m[n.casefold()]
    return None

def text(c,default="''"): return f"trim(cast({qi(c)} as varchar))" if c else default

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--award-suppliers',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=4");con.execute("SET memory_limit='12GB'")
    hp,apath,bp=map(Path,(a.historical,a.awards,a.award_suppliers))
    hc={r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(hp)]).fetchall()}; ac={r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(apath)]).fetchall()}; bc={r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(bp)]).fetchall()}

    hs=choose(hc,'Warehouse_Source','source','source_name'); ht=choose(hc,'Historical_Tender_ID','record_id','notice_id','id'); hcountry=choose(hc,'Country','country','country_code','Buyer_Country'); hbi=choose(hc,'Buyer_ID','buyer_id'); hbn=choose(hc,'Buyer_Name','buyer_name','buyer'); hcur=choose(hc,'Currency','currency'); hlean=choose(hc,'Lean_Fit','lean_fit'); hest=choose(hc,'Official_Estimated_Value','estimated_value'); hpub=choose(hc,'Publication_Date','publication_date'); htitle=choose(hc,'Title','title'); hscope=choose(hc,'Scope_Summary','description','scope_summary'); hcpv=choose(hc,'CPV_NAICS_or_Local_Code','CPV','cpv','cpv_code','main_cpv','classification_id'); hcpvd=choose(hc,'Raw_CPV_Description','cpv_description','classification_description'); hspend=choose(hc,'Raw_Spend_Category','main_procurement_category'); hproc=choose(hc,'Procedure','procedure','Competition_Type','procurement_method'); hparent=choose(hc,'Parent_Agreement_ID','parent_agreement_id'); hurl=choose(hc,'Primary_Source_URL','Official_URL','official_url','source_url','url')
    aas=choose(ac,'Warehouse_Source','source','source_name'); aat=choose(ac,'Historical_Tender_ID','historical_tender_id','record_id','notice_id'); aa=choose(ac,'Award_ID','award_id','id'); av=choose(ac,'Award_Value','award_value','value'); acur=choose(ac,'Currency','currency','award_currency'); abid=choose(ac,'Bidder_Count','bidder_count','number_of_bids','bids_received'); ascope=choose(ac,'Award_Value_Scope','award_value_scope');
    bs=choose(bc,'Warehouse_Source','source','source_name'); ba=choose(bc,'Award_ID','award_id'); bsi=choose(bc,'Supplier_ID','supplier_id'); bsn=choose(bc,'Supplier_Name','supplier_name','name')
    req={'historical source':hs,'tender id':ht,'buyer':hbn,'award source':aas,'award tender':aat,'award id':aa,'bridge source':bs,'bridge award':ba,'bridge supplier':bsi}
    miss=[k for k,v in req.items() if not v]
    if miss: raise SystemExit(json.dumps({'missing':miss,'historical_columns':sorted(hc),'award_columns':sorted(ac),'bridge_columns':sorted(bc)},indent=2))

    source=text(hs);tid=text(ht);country=f"upper({text(hcountry)})" if hcountry else f"upper({source})";buyer_name=text(hbn);buyer_id=text(hbi,"''");buyer_key=f"lower(regexp_replace(coalesce(nullif({buyer_id},''),{buyer_name}),'\\s+',' ','g'))";currency=f"upper(coalesce(nullif({text(hcur)},''),'UNKNOWN'))" if hcur else "'UNKNOWN'";lean=f"try_cast({qi(hlean)} AS DOUBLE)" if hlean else 'NULL::DOUBLE';est=f"try_cast({qi(hest)} AS DOUBLE)" if hest else 'NULL::DOUBLE';pub=f"try_cast({qi(hpub)} AS DATE)" if hpub else 'NULL::DATE';title=text(htitle,"''");scope=text(hscope,"''");cpv=text(hcpv,"''");cpvd=text(hcpvd,"''");spend=text(hspend,"''");proc=text(hproc,"''");parent=text(hparent,"''");url=text(hurl,"''")
    asrc=text(aas);atid=text(aat);aid=text(aa);awardval=f"try_cast({qi(av)} AS DOUBLE)" if av else 'NULL::DOUBLE';awardcur=f"upper(coalesce(nullif({text(acur)},''),'UNKNOWN'))" if acur else "'UNKNOWN'";bid=f"try_cast({qi(abid)} AS DOUBLE)" if abid else 'NULL::DOUBLE';awscope=text(ascope,"'UNKNOWN'")
    bsrc=text(bs);baid=text(ba);bsid=text(bsi);bsname=text(bsn,"''")

    # Strict, action-oriented lane classifier. Generic words such as communication, content,
    # interpretation, metadata and balayage are deliberately NOT sufficient on their own.
    txt=f"lower(concat_ws(' ',{title},{scope},{cpvd},{spend}))"
    lane_case=f"""
      CASE
        WHEN regexp_matches({txt}, '(website|web site|site web|site internet|\\bcms\\b|content management system|gestionnaire de contenu|gestion de contenu|wordpress|drupal|joomla|portail web|web portal|internetauftritt|webseite|sitio web|sito web)')
             AND regexp_matches({txt}, '(maintenance|support|hosting|hébergement|hebergement|accessibil|wcag|barrierefrei|pflege|betrieb|operation)')
          THEN 'Website support / accessibility / hosting'
        WHEN regexp_matches({txt}, '(website|web site|site web|site internet|\\bcms\\b|content management system|gestionnaire de contenu|gestion de contenu|wordpress|drupal|joomla|portail web|web portal|internetauftritt|webseite|sitio web|sito web)')
          THEN 'Website / CMS build or redesign'
        WHEN regexp_matches({txt}, '(traduction|translation|translations|übersetz|uebersetz|traducción|traduccion|traduzione|tłumacz|tlumacz|linguistic translation)')
          THEN 'Translation'
        WHEN regexp_matches({txt}, '(transcription|transcribing|speech[- ]to[- ]text|captioning|closed caption|sous[- ]titr|subtitl)')
          THEN 'Transcription / captioning'
        WHEN regexp_matches({txt}, '(digitization|digitisation|digitalization|digitalisation|numérisation|numerisation|document scanning|scan of documents|scanning of documents|digitalisierung.{0,40}(akten|dokument)|\\bocr\\b)')
             AND NOT regexp_matches({txt}, '(street sweep|street cleaning|balayage.{0,30}(rue|voirie|chauss|trottoir)|road sweep|nettoyage.{0,30}(rue|voirie))')
          THEN 'Document digitization / OCR / scanning'
        WHEN regexp_matches({txt}, '(data entry|saisie de données|saisie de donnees|datenerfassung|entrada de datos|inserimento dati)')
          THEN 'Data entry / clerical processing'
        WHEN regexp_matches({txt}, '(graphic design|conception graphique|design graphique|graphisme|mise en page|desktop publishing|infograph|identité visuelle|identite visuelle|visual identity|grafikdesign|grafische gestaltung|diseño gráfico|diseno grafico|progettazione grafica)')
             AND NOT regexp_matches({txt}, '(architect|civil engineering|engineering design|construction design|road design)')
          THEN 'Graphic design / layout / DTP'
        WHEN regexp_matches({txt}, '(video production|production vidéo|production video|videoproduktion|post[- ]production|motion graphic|motion design|video edit|montage vidéo|montage video|film production)')
          THEN 'Video production / post-production'
        WHEN regexp_matches({txt}, '(social media|réseaux sociaux|reseaux sociaux|community management|social media management|gestion des médias sociaux|gestion des medias sociaux)')
          THEN 'Social media / community management'
        WHEN regexp_matches({txt}, '(search engine optimi|\\bseo\\b|référencement naturel|referencement naturel|digital marketing|marketing digital|online marketing)')
          THEN 'SEO / digital marketing'
        WHEN regexp_matches({txt}, '(media monitoring|press monitoring|veille médiatique|veille mediatique|revue de presse|medienbeobachtung)')
          THEN 'Media / press monitoring'
        WHEN regexp_matches({txt}, '(market research|étude de marché|etude de marche|opinion poll|sondage|survey services|customer survey)')
          THEN 'Survey / market research'
        WHEN regexp_matches({txt}, '(printing services|print production|services d.impression|travaux d.impression|imprimerie|printing and delivery|mise sous pli|mailing services|routage)')
             AND NOT regexp_matches({txt}, '(3d print|additive manufactur)')
          THEN 'Printing / mailing / routing'
        WHEN regexp_matches({txt}, '(promotional merchandise|promotional items|objets publicitaires|articles promotionnels|goodies)')
          THEN 'Promotional merchandise'
        WHEN regexp_matches({txt}, '(annual report|rapport annuel|publication production|document formatting|formatting of documents)')
             AND regexp_matches({txt}, '(design|layout|mise en page|production|publishing)')
          THEN 'Report / publication production'
        ELSE NULL
      END
    """
    framework=f"CASE WHEN nullif({parent},'') IS NOT NULL OR regexp_matches(lower(concat_ws(' ',{title},{scope},{proc})),'(framework agreement|\\bframework\\b|accord[- ]cadre|dynamic purchasing|\\bdps\\b|système d.acquisition dynamique|systeme d.acquisition dynamique|rahmenvereinbarung|sistema dinamico|sistema dinámico)') THEN 1 ELSE 0 END"

    con.execute(f"""CREATE TEMP TABLE tend AS SELECT {source} warehouse_source,{tid} tender_id,{country} country,{buyer_key} buyer_key,{buyer_name} buyer_name,{currency} currency,{lean} source_lean_fit,{est} estimated_value,{pub} publication_date,{title} title,{scope} scope_summary,{cpv} cpv_code,{cpvd} cpv_description,{proc} procedure,{parent} parent_agreement_id,{url} official_url,{framework} framework_like,{lane_case} clean_lane FROM read_parquet(?)""",[str(hp)])
    con.execute("DELETE FROM tend WHERE clean_lane IS NULL")
    con.execute(f"""CREATE TEMP TABLE aw AS SELECT {asrc} warehouse_source,{atid} tender_id,{aid} award_id,{awardval} award_value,{awardcur} award_currency,{bid} bidder_count,{awscope} award_value_scope FROM read_parquet(?)""",[str(apath)])
    con.execute(f"""CREATE TEMP TABLE br AS SELECT {bsrc} warehouse_source,{baid} award_id,{bsid} supplier_id,{bsname} supplier_name FROM read_parquet(?) WHERE nullif({bsid},'') IS NOT NULL""",[str(bp)])

    con.execute("""CREATE TEMP TABLE cohort_t AS SELECT warehouse_source,country,clean_lane,currency,count(DISTINCT tender_id) tender_count,count(DISTINCT buyer_key) FILTER(WHERE buyer_key<>'') unique_buyers,count(DISTINCT tender_id) FILTER(WHERE framework_like=0) direct_like_tenders,avg(CASE WHEN framework_like=0 THEN 1.0 ELSE 0.0 END)*100 direct_like_pct,median(estimated_value) FILTER(WHERE estimated_value>1 AND framework_like=0) median_direct_estimated_value,quantile_cont(estimated_value,.25) FILTER(WHERE estimated_value>1 AND framework_like=0) p25_direct_estimated_value,quantile_cont(estimated_value,.75) FILTER(WHERE estimated_value>1 AND framework_like=0) p75_direct_estimated_value,min(publication_date) first_publication_date,max(publication_date) last_publication_date FROM tend GROUP BY 1,2,3,4""")
    con.execute("""CREATE TEMP TABLE cohort_a AS SELECT t.warehouse_source,t.country,t.clean_lane,CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,count(DISTINCT a.award_id) FILTER(WHERE t.framework_like=0) direct_award_count,median(a.award_value) FILTER(WHERE a.award_value>1 AND t.framework_like=0) median_direct_award_value,quantile_cont(a.award_value,.10) FILTER(WHERE a.award_value>1 AND t.framework_like=0) p10_direct_award_value,quantile_cont(a.award_value,.25) FILTER(WHERE a.award_value>1 AND t.framework_like=0) p25_direct_award_value,quantile_cont(a.award_value,.75) FILTER(WHERE a.award_value>1 AND t.framework_like=0) p75_direct_award_value,quantile_cont(a.award_value,.90) FILTER(WHERE a.award_value>1 AND t.framework_like=0) p90_direct_award_value,median(a.bidder_count) FILTER(WHERE a.bidder_count IS NOT NULL AND a.bidder_count>=0 AND t.framework_like=0) median_direct_bidder_count,avg(CASE WHEN a.bidder_count IS NOT NULL AND a.bidder_count>=0 AND t.framework_like=0 THEN 1.0 WHEN t.framework_like=0 THEN 0.0 ELSE NULL END)*100 direct_bidder_coverage_pct,avg(CASE WHEN a.bidder_count=1 AND t.framework_like=0 THEN 1.0 WHEN a.bidder_count IS NOT NULL AND t.framework_like=0 THEN 0.0 ELSE NULL END)*100 direct_single_bid_pct,avg(CASE WHEN a.bidder_count<=3 AND t.framework_like=0 THEN 1.0 WHEN a.bidder_count IS NOT NULL AND t.framework_like=0 THEN 0.0 ELSE NULL END)*100 direct_le3_bidder_pct FROM tend t JOIN aw a USING(warehouse_source,tender_id) GROUP BY 1,2,3,4""")
    con.execute("""CREATE TEMP TABLE buyer_lane AS SELECT warehouse_source,country,clean_lane,currency,buyer_key,any_value(buyer_name) buyer_name,count(DISTINCT tender_id) FILTER(WHERE framework_like=0) direct_tender_count FROM tend WHERE buyer_key<>'' GROUP BY 1,2,3,4,5""")
    con.execute("""CREATE TEMP TABLE repeats AS SELECT warehouse_source,country,clean_lane,currency,count(*) FILTER(WHERE direct_tender_count>=3) repeat_buyer_count,count(*) FILTER(WHERE direct_tender_count>=5) strong_repeat_buyer_count FROM buyer_lane GROUP BY 1,2,3,4""")
    con.execute("""CREATE TEMP TABLE brf AS SELECT *,1.0/count(*) OVER(PARTITION BY warehouse_source,award_id) frac FROM br""")
    con.execute("""CREATE TEMP TABLE sx AS SELECT t.warehouse_source,t.country,t.clean_lane,CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,b.supplier_id,any_value(b.supplier_name) supplier_name,sum(b.frac) fractional_wins FROM tend t JOIN aw a USING(warehouse_source,tender_id) JOIN brf b USING(warehouse_source,award_id) WHERE t.framework_like=0 GROUP BY 1,2,3,4,5""")
    con.execute("""CREATE TEMP TABLE shares AS SELECT *,fractional_wins/nullif(sum(fractional_wins) OVER(PARTITION BY warehouse_source,country,clean_lane,currency),0) share FROM sx""")
    con.execute("""CREATE TEMP TABLE frag AS SELECT warehouse_source,country,clean_lane,currency,count(*) supplier_count,max(share)*100 top_supplier_share_pct,sum(share*share)*10000 supplier_hhi FROM shares GROUP BY 1,2,3,4""")
    con.execute("""CREATE TEMP TABLE cohort AS SELECT t.*,coalesce(a.direct_award_count,0) direct_award_count,a.median_direct_award_value,a.p10_direct_award_value,a.p25_direct_award_value,a.p75_direct_award_value,a.p90_direct_award_value,a.median_direct_bidder_count,a.direct_bidder_coverage_pct,a.direct_single_bid_pct,a.direct_le3_bidder_pct,coalesce(r.repeat_buyer_count,0) repeat_buyer_count,coalesce(r.strong_repeat_buyer_count,0) strong_repeat_buyer_count,f.supplier_count,f.top_supplier_share_pct,f.supplier_hhi FROM cohort_t t LEFT JOIN cohort_a a USING(warehouse_source,country,clean_lane,currency) LEFT JOIN repeats r USING(warehouse_source,country,clean_lane,currency) LEFT JOIN frag f USING(warehouse_source,country,clean_lane,currency)""")
    con.execute("""CREATE TEMP TABLE scored AS WITH b AS (SELECT *,percent_rank() OVER(ORDER BY direct_like_tenders) volume_pct,percent_rank() OVER(ORDER BY unique_buyers) buyer_pct,percent_rank() OVER(ORDER BY coalesce(repeat_buyer_count,0)) repeat_pct,percent_rank() OVER(ORDER BY -coalesce(supplier_hhi,10000)) fragmentation_pct,percent_rank() OVER(ORDER BY direct_like_pct) direct_pct FROM cohort WHERE tender_count>=10 AND direct_like_tenders>=5) SELECT *,CASE WHEN direct_bidder_coverage_pct>=30 AND median_direct_bidder_count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-median_direct_bidder_count)/7.0)) ELSE .5 END competition_score,round(100*(.20*volume_pct+.20*buyer_pct+.15*repeat_pct+.15*fragmentation_pct+.15*direct_pct+.15*CASE WHEN direct_bidder_coverage_pct>=30 AND median_direct_bidder_count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-median_direct_bidder_count)/7.0)) ELSE .5 END),2) clean_opportunity_score FROM b""")

    rankp=out/'clean_lane_rank.csv';con.execute(f"COPY (SELECT *,CASE WHEN direct_bidder_coverage_pct>=30 THEN 'COMPETITION_OBSERVED' ELSE 'COMPETITION_LOW_COVERAGE_NEUTRAL' END competition_status,'STRICT_TEXT_RECLASSIFIED_PRE_DCE' derived_status FROM scored ORDER BY clean_opportunity_score DESC,direct_like_tenders DESC) TO '{rankp.as_posix()}' (HEADER)")
    con.execute(f"COPY (SELECT * FROM buyer_lane WHERE direct_tender_count>=3 ORDER BY direct_tender_count DESC) TO '{(out/'clean_repeat_buyers.csv').as_posix()}' (HEADER)")
    con.execute(f"COPY (WITH r AS (SELECT *,row_number() OVER(PARTITION BY warehouse_source,country,clean_lane,currency ORDER BY fractional_wins DESC,supplier_id) rn,share*100 supplier_share_pct FROM shares) SELECT * EXCLUDE(rn,share) FROM r WHERE rn<=10 ORDER BY warehouse_source,country,clean_lane,currency,rn) TO '{(out/'clean_winners.csv').as_posix()}' (HEADER)")
    con.execute(f"COPY (SELECT warehouse_source,country,clean_lane,currency,month(publication_date) month,count(DISTINCT tender_id) direct_tenders FROM tend WHERE framework_like=0 AND publication_date IS NOT NULL GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5) TO '{(out/'clean_seasonality_monthly.csv').as_posix()}' (HEADER)")

    # Representative examples: direct-like, with award value close to lane median and low observed competition first.
    con.execute(f"""COPY (WITH x AS (SELECT t.warehouse_source,t.country,t.clean_lane,CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,t.tender_id,t.title,t.buyer_name,t.publication_date,t.cpv_code,t.cpv_description,t.procedure,t.official_url,a.award_id,a.award_value,a.award_value_scope,a.bidder_count,c.median_direct_award_value,string_agg(DISTINCT nullif(b.supplier_name,''),' | ') supplier_names FROM tend t JOIN aw a USING(warehouse_source,tender_id) JOIN cohort c ON c.warehouse_source=t.warehouse_source AND c.country=t.country AND c.clean_lane=t.clean_lane AND c.currency=(CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END) LEFT JOIN br b USING(warehouse_source,award_id) WHERE t.framework_like=0 GROUP BY ALL),r AS (SELECT *,row_number() OVER(PARTITION BY warehouse_source,country,clean_lane,currency ORDER BY CASE WHEN bidder_count IS NULL THEN 99 ELSE bidder_count END ASC,CASE WHEN award_value>0 AND median_direct_award_value>0 THEN abs(ln((award_value+1)/(median_direct_award_value+1))) ELSE 99 END ASC,tender_id) rn FROM x) SELECT * EXCLUDE(rn) FROM r WHERE rn<=10 ORDER BY warehouse_source,country,clean_lane,currency,rn) TO '{(out/'clean_examples.csv').as_posix()}' (HEADER)""")

    # Top CPV/local codes per clean lane for semantic QA.
    con.execute(f"COPY (WITH x AS (SELECT warehouse_source,country,clean_lane,currency,cpv_code,any_value(cpv_description) cpv_description,count(DISTINCT tender_id) direct_tenders FROM tend WHERE framework_like=0 AND nullif(cpv_code,'') IS NOT NULL GROUP BY 1,2,3,4,5),r AS (SELECT *,row_number() OVER(PARTITION BY warehouse_source,country,clean_lane,currency ORDER BY direct_tenders DESC,cpv_code) rn FROM x) SELECT * EXCLUDE(rn) FROM r WHERE rn<=10) TO '{(out/'clean_cpv_codes.csv').as_posix()}' (HEADER)")

    # Build compact top-50 JSON by reading outputs with Python-friendly DuckDB results.
    cur=con.execute("SELECT * FROM scored ORDER BY clean_opportunity_score DESC,direct_like_tenders DESC LIMIT 50"); cols=[d[0] for d in cur.description]; top=[dict(zip(cols,r)) for r in cur.fetchall()]
    def read_csv(name):
        with open(out/name,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    ex=read_csv('clean_examples.csv');win=read_csv('clean_winners.csv');rb=read_csv('clean_repeat_buyers.csv');cpvs=read_csv('clean_cpv_codes.csv');months=read_csv('clean_seasonality_monthly.csv')
    def k(r):return tuple(str(r.get(x,'')) for x in ('warehouse_source','country','clean_lane','currency'))
    eidx={};widx={};ridx={};cidx={};midx={}
    for rows_,idx,lim in ((ex,eidx,5),(win,widx,5),(rb,ridx,8),(cpvs,cidx,8)):
        for z in rows_:idx.setdefault(k(z),[]).append(z)
        for kk in idx:idx[kk]=idx[kk][:lim]
    for z in months:midx.setdefault(k(z),[]).append(z)
    deep=[]
    for i,r in enumerate(top,1):
        kk=k(r); ms=midx.get(kk,[]); peak=max(ms,key=lambda x:float(x.get('direct_tenders') or 0),default=None)
        deep.append({'rank':i,'cohort':r,'top_repeat_buyers':ridx.get(kk,[]),'top_winners':widx.get(kk,[]),'top_codes':cidx.get(kk,[]),'representative_examples':eidx.get(kk,[]),'peak_month':peak})
    summary={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'strict_classifier_notes':['Generic communication/content is not enough for creative classification.','Balayage is excluded from digitization unless explicit digitization/OCR language exists.','Generic interpretation is not enough for language classification.','Framework/DPS-like tenders are separated from direct-like opportunity metrics.','Examples are selected near the direct-like median after preferring lower observed bidder counts.'],'source_columns':{'title':htitle,'scope':hscope,'cpv':hcpv,'cpv_description':hcpvd,'procedure':hproc,'parent_agreement':hparent},'top_50':deep}
    (out/'clean_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

    md=['# SPM Market Intelligence v6 — Clean lanes','','Strict semantic reclassification on Global Core v4; frameworks/DPS separated from direct-like metrics. Historical evidence only, not a live bid verdict.','','## Top clean lanes','','|#|Source / country|Clean lane|Direct-like tenders|Buyers|Direct %|Median direct award|Median bidders|Single-bid|Repeat buyers|Top supplier|Score|','|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(top,1):
        md.append(f"|{i}|{r['warehouse_source']} / {r['country']}|{r['clean_lane']}|{r['direct_like_tenders']:,}|{r['unique_buyers']:,}|{(r['direct_like_pct'] or 0):.1f}%|{r['currency']} {r['median_direct_award_value'] if r['median_direct_award_value'] is not None else 'NA'}|{r['median_direct_bidder_count'] if r['median_direct_bidder_count'] is not None else 'NA'}|{(r['direct_single_bid_pct'] or 0):.1f}%|{r['repeat_buyer_count']:,}|{(r['top_supplier_share_pct'] or 0):.1f}%|{r['clean_opportunity_score']:.2f}|")
    md+=['','## Deep evidence — top 20','']
    for item in deep[:20]:
        r=item['cohort'];md+=[f"### {item['rank']}. {r['warehouse_source']} / {r['country']} — {r['clean_lane']}",'',f"- Direct-like tenders: {r['direct_like_tenders']} / {r['tender_count']} ({r['direct_like_pct']:.1f}%), buyers {r['unique_buyers']}, median award {r['currency']} {r['median_direct_award_value']}, median bidders {r['median_direct_bidder_count']}, bidder coverage {r['direct_bidder_coverage_pct']}, single-bid {r['direct_single_bid_pct']}%, repeat buyers {r['repeat_buyer_count']}, supplier HHI {r['supplier_hhi']}."]
        if item['peak_month']:md.append(f"- Peak month: {item['peak_month'].get('month')} ({item['peak_month'].get('direct_tenders')} direct-like tenders).")
        if item['top_codes']:md.append('- Top codes: '+'; '.join(f"{x.get('cpv_code')} {x.get('cpv_description') or ''} ({x.get('direct_tenders')})" for x in item['top_codes'][:5]))
        if item['top_repeat_buyers']:md.append('- Repeat buyers: '+'; '.join(f"{x.get('buyer_name')} ({x.get('direct_tender_count')})" for x in item['top_repeat_buyers'][:5]))
        if item['top_winners']:md.append('- Winners: '+'; '.join(f"{x.get('supplier_name') or x.get('supplier_id')} ({x.get('supplier_share_pct')}%)" for x in item['top_winners'][:5]))
        if item['representative_examples']:
            md.append('- Representative examples:')
            for x in item['representative_examples'][:5]:md.append(f"  - {x.get('title')} — {x.get('buyer_name')} — {x.get('currency')} {x.get('award_value')} — bidders {x.get('bidder_count')} — {x.get('supplier_names') or 'UNKNOWN'} — code {x.get('cpv_code') or 'NA'}")
        md.append('')
    md+=['## QA warnings','', '- Strict regex materially improves precision but does not prove every record is in-scope.', '- Historical competition does not prove future competition.', '- Buyer eligibility, geography, references, turnover and procurement-route access still require live/DCE verification.']
    (out/'REPORT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','clean_tenders':con.execute('SELECT count(*) FROM tend').fetchone()[0],'ranked_lanes':con.execute('SELECT count(*) FROM scored').fetchone()[0],'top10':top[:10]},ensure_ascii=False,indent=2,default=str))

if __name__=='__main__':main()
