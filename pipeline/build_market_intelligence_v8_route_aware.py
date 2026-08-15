#!/usr/bin/env python3
from __future__ import annotations

"""Route-aware historical procurement intelligence for SPM.

Separates two fundamentally different commercial motions:
1. OPEN_BID: historical public/open competitive procurement that a supplier could
   plausibly discover and bid into, subject to live/DCE eligibility.
2. DIRECT_BUYER: historical direct/non-competitive procurement that is useful as
   buyer-demand / outbound / relationship evidence, but must never be presented
   as low-competition open tender evidence.

Global Core v4 notice-first only. Currency-isolated. Historical priors only.
"""

import argparse, csv, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
import duckdb

VERSION = "SPM_MARKET_INTELLIGENCE_V8_ROUTE_AWARE"


def qi(x: str) -> str:
    return '"' + x.replace('"','""') + '"'


def choose(cols: set[str], *names: str) -> str | None:
    m={c.casefold():c for c in cols}
    for n in names:
        if n.casefold() in m: return m[n.casefold()]
    return None


def txt(c: str | None, default: str="''") -> str:
    return f"trim(cast({qi(c)} as varchar))" if c else default


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--historical',required=True); p.add_argument('--awards',required=True); p.add_argument('--award-suppliers',required=True); p.add_argument('--out',required=True)
    a=p.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    hp,ap,bp=Path(a.historical),Path(a.awards),Path(a.award_suppliers)
    con=duckdb.connect(); con.execute("SET preserve_insertion_order=false"); con.execute("SET threads=4"); con.execute("SET memory_limit='12GB'")
    hc={r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(hp)]).fetchall()}
    ac={r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(ap)]).fetchall()}
    bc={r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(bp)]).fetchall()}

    hs=choose(hc,'Warehouse_Source'); ht=choose(hc,'Historical_Tender_ID'); hcountry=choose(hc,'Country'); hbi=choose(hc,'Buyer_ID'); hbn=choose(hc,'Buyer_Name'); hcur=choose(hc,'Currency'); hest=choose(hc,'Official_Estimated_Value'); hpub=choose(hc,'Publication_Date'); htitle=choose(hc,'Title'); hscope=choose(hc,'Scope_Summary'); hcpv=choose(hc,'CPV_NAICS_or_Local_Code'); hcpvd=choose(hc,'Raw_CPV_Description'); hproc=choose(hc,'Procedure'); hparent=choose(hc,'Parent_Agreement_ID'); hurl=choose(hc,'Primary_Source_URL')
    aas=choose(ac,'Warehouse_Source'); aat=choose(ac,'Historical_Tender_ID'); aidc=choose(ac,'Award_ID'); aval=choose(ac,'Award_Value'); acur=choose(ac,'Currency'); abid=choose(ac,'Bidder_Count'); ascope=choose(ac,'Award_Value_Scope')
    bs=choose(bc,'Warehouse_Source'); ba=choose(bc,'Award_ID'); bsi=choose(bc,'Supplier_ID'); bsn=choose(bc,'Supplier_Name')
    req={'h.source':hs,'h.id':ht,'h.buyer':hbn,'h.title':htitle,'h.procedure':hproc,'a.source':aas,'a.tender':aat,'a.id':aidc,'b.source':bs,'b.award':ba,'b.supplier':bsi}
    miss=[k for k,v in req.items() if not v]
    if miss: raise SystemExit(json.dumps({'missing':miss,'historical':sorted(hc),'awards':sorted(ac),'bridge':sorted(bc)},indent=2))

    source=txt(hs); tid=txt(ht); country=f"upper({txt(hcountry)})" if hcountry else f"upper({source})"; buyer_name=txt(hbn); buyer_id=txt(hbi,"''"); buyer_key=f"lower(regexp_replace(coalesce(nullif({buyer_id},''),{buyer_name}),'\\s+',' ','g'))"; currency=f"upper(coalesce(nullif({txt(hcur)},''),'UNKNOWN'))" if hcur else "'UNKNOWN'"; est=f"try_cast({qi(hest)} AS DOUBLE)" if hest else 'NULL::DOUBLE'; pub=f"try_cast({qi(hpub)} AS DATE)" if hpub else 'NULL::DATE'; title=txt(htitle); scope=txt(hscope,"''"); cpv=txt(hcpv,"''"); cpvd=txt(hcpvd,"''"); proc=txt(hproc,"'UNKNOWN'"); parent=txt(hparent,"''"); url=txt(hurl,"''")
    asrc=txt(aas); atid=txt(aat); aid=txt(aidc); av=f"try_cast({qi(aval)} AS DOUBLE)" if aval else 'NULL::DOUBLE'; awardcur=f"upper(coalesce(nullif({txt(acur)},''),'UNKNOWN'))" if acur else "'UNKNOWN'"; bidder=f"try_cast({qi(abid)} AS DOUBLE)" if abid else 'NULL::DOUBLE'; awscope=txt(ascope,"'UNKNOWN'")
    bsrc=txt(bs); baid=txt(ba); bsid=txt(bsi); bsname=txt(bsn,"''")

    t=f"lower(coalesce({title},''))"
    # High-precision title-led service lanes. Precision is preferred over recall.
    lane=f"""
    CASE
      WHEN regexp_matches({t}, '(website|web site|site web|site internet|content management system|gestionnaire de contenu|gestion de contenu|wordpress|drupal|joomla|portail web|web portal|internetauftritt|webseite|sitio web|sito web)')
           AND regexp_matches({t}, '(maintenance|support|hosting|hébergement|hebergement|accessibil|wcag|barrierefrei|pflege|betrieb|operation|entretien|mise à jour|mise a jour)')
        THEN 'Website support / accessibility / hosting'
      WHEN regexp_matches({t}, '(website|web site|site web|site internet|content management system|gestionnaire de contenu|gestion de contenu|wordpress|drupal|joomla|portail web|web portal|internetauftritt|webseite|sitio web|sito web)')
        THEN 'Website / CMS build or redesign'
      WHEN regexp_matches({t}, '(traduction|\\btranslations?\\b|translation services?|übersetz|uebersetz|traducción|traduccion|traduzione|tłumacz|tlumacz|linguistic translation)')
           AND NOT regexp_matches({t}, '(translational|translationale|translationell)')
        THEN 'Translation'
      WHEN regexp_matches({t}, '(transcription|transcribing|speech[- ]to[- ]text|captioning|closed caption|sous[- ]titr|subtitl|sténograph|stenograph)')
        THEN 'Transcription / captioning'
      WHEN regexp_matches({t}, '(digitization|digitisation|digitalization|digitalisation|numérisation|numerisation|document scanning|scan of documents|scanning of documents|digitalisierung.{0,40}(akten|dokument)|\\bocr\\b)')
           AND NOT regexp_matches({t}, '(street sweep|street cleaning|balayage.{0,30}(rue|voirie|chauss|trottoir)|road sweep|nettoyage.{0,30}(rue|voirie))')
        THEN 'Document digitization / OCR / scanning'
      WHEN regexp_matches({t}, '(data entry|saisie de données|saisie de donnees|entrada de datos|inserimento dati)')
        THEN 'Data entry / clerical processing'
      WHEN regexp_matches({t}, '(graphic design|conception graphique|design graphique|graphisme|mise en page|desktop publishing|infograph|identité visuelle|identite visuelle|visual identity|grafikdesign|grafische gestaltung|diseño gráfico|diseno grafico|progettazione grafica)')
           AND NOT regexp_matches({t}, '(architect|civil engineering|engineering design|construction design|road design|maîtrise d.oeuvre|maitrise d.oeuvre)')
        THEN 'Graphic design / layout / DTP'
      WHEN regexp_matches({t}, '(video production|production vidéo|production video|videoproduktion|post[- ]production|motion graphic|motion design|video edit|montage vidéo|montage video|film production)')
        THEN 'Video production / post-production'
      WHEN regexp_matches({t}, '(social media|réseaux sociaux|reseaux sociaux|community management|social media management|gestion des médias sociaux|gestion des medias sociaux)')
        THEN 'Social media / community management'
      WHEN regexp_matches({t}, '(search engine optimi|\\bseo\\b|référencement naturel|referencement naturel|digital marketing|marketing digital|online marketing)')
        THEN 'SEO / digital marketing'
      WHEN regexp_matches({t}, '(media monitoring|press monitoring|veille médiatique|veille mediatique|revue de presse|medienbeobachtung)')
        THEN 'Media / press monitoring'
      WHEN regexp_matches({t}, '(market research|étude de marché|etude de marche|opinion poll|sondage|survey services|customer survey)')
           AND NOT regexp_matches({t}, '(géotech|geotech|piézocône|piezocone|forage|sondage de sol|soil boring|drilling|borehole|géologique|geologique)')
        THEN 'Survey / market research'
      WHEN regexp_matches({t}, '(printing services|print production|services d.impression|travaux d.impression|imprimerie|printing and delivery|mise sous pli|mailing services|routage|impression et routage|impression,|impression de)')
           AND NOT regexp_matches({t}, '(3d print|additive manufactur|impression 3d)')
        THEN 'Printing / mailing / routing'
      WHEN regexp_matches({t}, '(promotional merchandise|promotional items|objets publicitaires|articles promotionnels|goodies)')
        THEN 'Promotional merchandise'
      WHEN regexp_matches({t}, '(annual report|rapport annuel|publication production|document formatting|formatting of documents)')
           AND regexp_matches({t}, '(design|layout|mise en page|production|publishing)')
        THEN 'Report / publication production'
      ELSE NULL
    END
    """

    # Route semantics are source-specific because canonical Procedure preserves national vocabulary.
    pl=f"lower(coalesce({proc},''))"
    sl=f"lower(coalesce({source},''))"
    framework_override=f"(nullif({parent},'') IS NOT NULL OR regexp_matches(lower(concat_ws(' ',{title},{scope},{proc})),'(framework agreement|\\bframework\\b|accord[- ]cadre|dynamic purchasing|\\bdps\\b|système d.acquisition dynamique|systeme d.acquisition dynamique|rahmenvereinbarung|sistema dinamico|sistema dinámico|award under framework|call-off)'))"
    route=f"""
    CASE
      WHEN {framework_override} THEN 'FRAMEWORK_DPS_CALLOFF'
      WHEN {sl}='quebec' THEN CASE
        WHEN {pl} LIKE '%gré à gré%' THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%invitation%' THEN 'LIMITED_INVITATION'
        WHEN {pl} LIKE '%achat mandaté%' OR {pl} LIKE '%regroupement d’organismes%' OR {pl} LIKE '%regroupement d''organismes%' THEN 'GROUPED_OR_MANDATED'
        WHEN ({pl} LIKE '%avis d’appel d’offres%' OR {pl} LIKE '%avis d''appel d''offres%') AND ({pl} LIKE '%régionalisé%' OR {pl} LIKE '%regionalise%' OR {pl} LIKE '%réservé%' OR {pl} LIKE '%reserve%') THEN 'OPEN_RESERVED_OR_REGIONAL'
        WHEN {pl} LIKE '%avis d’appel d’offres%' OR {pl} LIKE '%avis d''appel d''offres%' OR {pl} LIKE '%appel d’offres public%' OR {pl} LIKE '%appel d''offres public%' THEN 'OPEN_PUBLIC'
        ELSE 'UNKNOWN'
      END
      WHEN {sl}='canada federal' THEN CASE
        WHEN {pl}='competitive - open bidding' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('competitive - traditional','competitive - selective tendering','competitive - limited tendering') THEN 'COMPETITIVE_OTHER'
        WHEN {pl}='advance contract award notice' OR {pl}='non-competitive' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN'
      END
      WHEN {sl}='france' THEN CASE
        WHEN {pl} LIKE 'ouvert/%' OR {pl}='ouvert/' THEN 'OPEN_PUBLIC'
        WHEN {pl} LIKE 'procedure_adapte/%' OR {pl}='procedure_adapte/' OR {pl} LIKE 'restreint/%' OR {pl}='restreint/' OR {pl} LIKE '%avec_pub_prealable%' OR {pl} LIKE 'dialogue_competitif/%' THEN 'COMPETITIVE_OTHER'
        WHEN {pl} LIKE '%sans_pub%' OR {pl} LIKE 'attribue_sans_pub%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN'
      END
      WHEN {sl}='germany' THEN CASE
        WHEN {pl} IN ('de-open','open','us-open') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted','de-restricted-w-call','neg-w-call','de-comp-w-call','de-comp-neg-w-call','comp-tend','comp-dial','us-neg-w-call','us-res-tw') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('neg-wo-call','de-restricted-wo-call','de-comp-wo-call','de-comp-neg-wo-call','oth-single','us-neg-wo-call','us-free-no-tw','us-res-no-tw') OR {pl} LIKE '%freihändige%' OR {pl} LIKE '%freihandige%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN'
      END
      WHEN {sl}='ireland' THEN CASE
        WHEN {pl}='open procedure' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','competitive procedure with negotiation','simplified','competitive dialogue') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('direct invite – mini-competition','dps qualification','uqs qualification') THEN 'FRAMEWORK_DPS_CALLOFF'
        WHEN {pl} IN ('negotiated procedure without prior publication','direct invite – quick quote') THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN'
      END
      WHEN {sl}='united kingdom' THEN CASE
        WHEN {pl} IN ('open procedure','below threshold - open competition','competitive flexible procedure','competitive tendering procedure') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','restricted','below threshold - limited competition','negotiated procedure with prior call for competition','competitive procedure with negotiation','competitive dialogue','negotiated with publication of a contract notice','award procedure with prior publication of a call for competition','procedure involving negotiations') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('below threshold - without competition','award procedure without prior publication of a call for competition','direct award','negotiated without publication of a contract notice') THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%framework%' OR {pl} LIKE '%dynamic market%' THEN 'FRAMEWORK_DPS_CALLOFF'
        ELSE 'UNKNOWN'
      END
      ELSE 'UNKNOWN'
    END
    """

    con.execute(f"""CREATE TEMP TABLE tend AS SELECT {source} warehouse_source,{tid} tender_id,{country} country,{buyer_key} buyer_key,{buyer_name} buyer_name,{currency} currency,{est} estimated_value,{pub} publication_date,{title} title,{cpv} cpv_code,{cpvd} cpv_description,{proc} procurement_procedure,{url} official_url,{lane} lane,{route} route_band FROM read_parquet(?)""",[str(hp)])
    con.execute("DELETE FROM tend WHERE lane IS NULL")
    con.execute(f"""CREATE TEMP TABLE aw AS SELECT {asrc} warehouse_source,{atid} tender_id,{aid} award_id,{av} award_value,{awardcur} award_currency,{bidder} bidder_count,{awscope} award_value_scope FROM read_parquet(?)""",[str(ap)])
    con.execute(f"""CREATE TEMP TABLE br AS SELECT {bsrc} warehouse_source,{baid} award_id,{bsid} supplier_id,{bsname} supplier_name FROM read_parquet(?) WHERE nullif({bsid},'') IS NOT NULL""",[str(bp)])

    # Route mix by lane.
    con.execute("""CREATE TEMP TABLE route_counts AS SELECT warehouse_source,country,lane,currency,route_band,count(DISTINCT tender_id) tender_count,count(DISTINCT buyer_key) FILTER(WHERE buyer_key<>'') buyer_count FROM tend GROUP BY 1,2,3,4,5""")
    con.execute(f"COPY (SELECT * FROM route_counts ORDER BY warehouse_source,country,lane,currency,tender_count DESC) TO '{(out/'route_mix.csv').as_posix()}' (HEADER)")

    # Buyer recurrence at lane+route level.
    con.execute("""CREATE TEMP TABLE buyer_route AS SELECT warehouse_source,country,lane,currency,route_band,buyer_key,any_value(buyer_name) buyer_name,count(DISTINCT tender_id) tender_count FROM tend WHERE buyer_key<>'' GROUP BY 1,2,3,4,5,6""")
    con.execute(f"COPY (SELECT * FROM buyer_route WHERE tender_count>=2 ORDER BY route_band,tender_count DESC) TO '{(out/'repeat_buyers_by_route.csv').as_posix()}' (HEADER)")

    # Fractional supplier wins prevent consortium multiplication.
    con.execute("""CREATE TEMP TABLE brf AS SELECT *,1.0/count(*) OVER(PARTITION BY warehouse_source,award_id) frac FROM br""")
    con.execute("""CREATE TEMP TABLE sup_route AS SELECT t.warehouse_source,t.country,t.lane,CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,t.route_band,b.supplier_id,any_value(b.supplier_name) supplier_name,sum(b.frac) fractional_wins FROM tend t JOIN aw a USING(warehouse_source,tender_id) JOIN brf b USING(warehouse_source,award_id) GROUP BY 1,2,3,4,5,6""")
    con.execute("""CREATE TEMP TABLE shares AS SELECT *,fractional_wins/nullif(sum(fractional_wins) OVER(PARTITION BY warehouse_source,country,lane,currency,route_band),0) supplier_share FROM sup_route""")
    con.execute("""CREATE TEMP TABLE frag AS SELECT warehouse_source,country,lane,currency,route_band,count(*) supplier_count,max(supplier_share)*100 top_supplier_share_pct,sum(supplier_share*supplier_share)*10000 supplier_hhi FROM shares GROUP BY 1,2,3,4,5""")

    # Facts per route. Monetary stats are currency-isolated.
    con.execute("""CREATE TEMP TABLE route_facts AS SELECT t.warehouse_source,t.country,t.lane,CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,t.route_band,count(DISTINCT t.tender_id) tender_count,count(DISTINCT t.buyer_key) FILTER(WHERE t.buyer_key<>'') unique_buyers,count(DISTINCT a.award_id) award_count,median(a.award_value) FILTER(WHERE a.award_value>100) median_award_value,quantile_cont(a.award_value,.25) FILTER(WHERE a.award_value>100) p25_award_value,quantile_cont(a.award_value,.75) FILTER(WHERE a.award_value>100) p75_award_value,median(a.bidder_count) FILTER(WHERE a.bidder_count IS NOT NULL AND a.bidder_count>=1) median_bidder_count,avg(CASE WHEN a.bidder_count IS NOT NULL AND a.bidder_count>=1 THEN 1.0 ELSE 0.0 END)*100 bidder_coverage_pct,avg(CASE WHEN a.bidder_count=1 THEN 1.0 WHEN a.bidder_count IS NOT NULL AND a.bidder_count>=1 THEN 0.0 ELSE NULL END)*100 single_bid_pct,avg(CASE WHEN a.bidder_count<=3 AND a.bidder_count>=1 THEN 1.0 WHEN a.bidder_count IS NOT NULL AND a.bidder_count>=1 THEN 0.0 ELSE NULL END)*100 le3_bidder_pct FROM tend t LEFT JOIN aw a USING(warehouse_source,tender_id) GROUP BY 1,2,3,4,5""")
    con.execute("""CREATE TEMP TABLE repeats AS SELECT warehouse_source,country,lane,currency,route_band,count(*) FILTER(WHERE tender_count>=3) repeat_buyer_count,count(*) FILTER(WHERE tender_count>=5) strong_repeat_buyer_count FROM buyer_route GROUP BY 1,2,3,4,5""")
    con.execute("""CREATE TEMP TABLE facts AS SELECT f.*,coalesce(r.repeat_buyer_count,0) repeat_buyer_count,coalesce(r.strong_repeat_buyer_count,0) strong_repeat_buyer_count,g.supplier_count,g.top_supplier_share_pct,g.supplier_hhi FROM route_facts f LEFT JOIN repeats r USING(warehouse_source,country,lane,currency,route_band) LEFT JOIN frag g USING(warehouse_source,country,lane,currency,route_band)""")
    con.execute(f"COPY (SELECT * FROM facts ORDER BY route_band,tender_count DESC) TO '{(out/'route_facts.csv').as_posix()}' (HEADER)")

    # OPEN score: only OPEN_PUBLIC rows. Low bidder counts only contribute when coverage >=30%.
    con.execute("""CREATE TEMP TABLE open_scored AS WITH b AS (SELECT *,percent_rank() OVER(ORDER BY tender_count) volume_pct,percent_rank() OVER(ORDER BY unique_buyers) breadth_pct,percent_rank() OVER(ORDER BY repeat_buyer_count) repeat_pct,percent_rank() OVER(ORDER BY -coalesce(supplier_hhi,10000)) fragmentation_pct,percent_rank() OVER(ORDER BY coalesce(award_count,0)) award_evidence_pct FROM facts WHERE route_band='OPEN_PUBLIC' AND tender_count>=5), s AS (SELECT *,CASE WHEN bidder_coverage_pct>=30 AND median_bidder_count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-median_bidder_count)/7.0)) ELSE .5 END competition_score FROM b) SELECT *,round(100*(.25*volume_pct+.22*breadth_pct+.13*repeat_pct+.15*fragmentation_pct+.17*competition_score+.08*award_evidence_pct),2) open_bid_score FROM s""")
    con.execute(f"COPY (SELECT *,'HISTORICAL_OPEN_PUBLIC_ONLY_PRE_DCE' derived_status FROM open_scored ORDER BY open_bid_score DESC,tender_count DESC) TO '{(out/'open_bid_rank.csv').as_posix()}' (HEADER)")

    # DIRECT buyer score: relationship/outbound demand, never interpreted as tender competition.
    con.execute("""CREATE TEMP TABLE direct_scored AS WITH b AS (SELECT *,percent_rank() OVER(ORDER BY tender_count) volume_pct,percent_rank() OVER(ORDER BY unique_buyers) breadth_pct,percent_rank() OVER(ORDER BY repeat_buyer_count) repeat_pct,percent_rank() OVER(ORDER BY -coalesce(supplier_hhi,10000)) fragmentation_pct,percent_rank() OVER(ORDER BY coalesce(award_count,0)) award_evidence_pct FROM facts WHERE route_band='DIRECT_NONCOMPETITIVE' AND tender_count>=5) SELECT *,round(100*(.30*volume_pct+.25*breadth_pct+.20*repeat_pct+.15*fragmentation_pct+.10*award_evidence_pct),2) direct_buyer_score FROM b""")
    con.execute(f"COPY (SELECT *,'BUYER_OUTREACH_EVIDENCE_NOT_OPEN_COMPETITION' derived_status FROM direct_scored ORDER BY direct_buyer_score DESC,tender_count DESC) TO '{(out/'direct_buyer_rank.csv').as_posix()}' (HEADER)")

    # Invitation / competitive-other are separate evidence lanes.
    con.execute(f"COPY (SELECT * FROM facts WHERE route_band IN ('LIMITED_INVITATION','COMPETITIVE_OTHER','OPEN_RESERVED_OR_REGIONAL','GROUPED_OR_MANDATED','FRAMEWORK_DPS_CALLOFF') ORDER BY route_band,tender_count DESC) TO '{(out/'other_route_rank.csv').as_posix()}' (HEADER)")

    # Top winners by route/lane.
    con.execute(f"""COPY (WITH r AS (SELECT *,row_number() OVER(PARTITION BY warehouse_source,country,lane,currency,route_band ORDER BY fractional_wins DESC,supplier_id) rn,supplier_share*100 supplier_share_pct FROM shares) SELECT * EXCLUDE(rn,supplier_share) FROM r WHERE rn<=8 ORDER BY route_band,warehouse_source,country,lane,currency,rn) TO '{(out/'winners_by_route.csv').as_posix()}' (HEADER)""")

    # Examples prioritize values around the route/lane median and low observed bidders for open routes.
    con.execute(f"""COPY (WITH sn AS (SELECT warehouse_source,award_id,string_agg(DISTINCT nullif(supplier_name,''),' | ') supplier_names FROM br GROUP BY 1,2), x AS (SELECT t.warehouse_source,t.country,t.lane,CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,t.route_band,t.tender_id,t.title,t.buyer_name,t.publication_date,t.cpv_code,t.cpv_description,t.procurement_procedure,t.official_url,a.award_id,a.award_value,a.bidder_count,sn.supplier_names,f.median_award_value FROM tend t LEFT JOIN aw a USING(warehouse_source,tender_id) LEFT JOIN sn USING(warehouse_source,award_id) LEFT JOIN facts f ON f.warehouse_source=t.warehouse_source AND f.country=t.country AND f.lane=t.lane AND f.currency=(CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END) AND f.route_band=t.route_band), r AS (SELECT *,row_number() OVER(PARTITION BY warehouse_source,country,lane,currency,route_band ORDER BY CASE WHEN route_band='OPEN_PUBLIC' AND bidder_count IS NOT NULL THEN bidder_count ELSE 99 END,CASE WHEN award_value>100 AND median_award_value>100 THEN abs(ln((award_value+1)/(median_award_value+1))) ELSE 99 END,tender_id) rn FROM x) SELECT * EXCLUDE(rn) FROM r WHERE rn<=6 ORDER BY route_band,warehouse_source,country,lane,currency) TO '{(out/'examples_by_route.csv').as_posix()}' (HEADER)""")

    # Route seasonality.
    con.execute(f"COPY (SELECT warehouse_source,country,lane,currency,route_band,month(publication_date) publication_month,count(DISTINCT tender_id) tender_count FROM tend WHERE publication_date IS NOT NULL GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6) TO '{(out/'seasonality_by_route.csv').as_posix()}' (HEADER)")

    # Compact GPT snapshot.
    def readcsv(name):
        with open(out/name,encoding='utf-8-sig',newline='') as fh:return list(csv.DictReader(fh))
    opens=readcsv('open_bid_rank.csv'); directs=readcsv('direct_buyer_rank.csv'); ex=readcsv('examples_by_route.csv'); wins=readcsv('winners_by_route.csv'); reps=readcsv('repeat_buyers_by_route.csv'); mix=readcsv('route_mix.csv')
    def k(r): return tuple(r.get(x,'') for x in ('warehouse_source','country','lane','currency','route_band'))
    exi={}; wi={}; ri={}; mi={}
    for z in ex: exi.setdefault(k(z),[]).append(z)
    for z in wins: wi.setdefault(k(z),[]).append(z)
    for z in reps: ri.setdefault(k(z),[]).append(z)
    for z in mix: mi.setdefault(tuple(z.get(x,'') for x in ('warehouse_source','country','lane','currency')),[]).append(z)
    for d in (exi,wi,ri):
        for kk in d:d[kk]=d[kk][:6]
    def enrich(rows,band,limit=30):
        ans=[]
        for i,r in enumerate(rows[:limit],1):
            kk=(r.get('warehouse_source',''),r.get('country',''),r.get('lane',''),r.get('currency',''),band)
            base=(r.get('warehouse_source',''),r.get('country',''),r.get('lane',''),r.get('currency',''))
            ans.append({'rank':i,'cohort':r,'route_mix':mi.get(base,[]),'top_repeat_buyers':ri.get(kk,[]),'top_winners':wi.get(kk,[]),'examples':exi.get(kk,[])})
        return ans
    snapshot={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'open_bid_top30':enrich(opens,'OPEN_PUBLIC'),'direct_buyer_top30':enrich(directs,'DIRECT_NONCOMPETITIVE'),'guardrails':['OPEN_BID scores use OPEN_PUBLIC historical rows only.','DIRECT_BUYER scores are relationship/outbound evidence, not evidence of an open tender or low competition.','Invitation, reserved/regional, framework/DPS and competitive-other routes remain separate.','All monetary cohorts are currency-isolated.','Historical evidence never satisfies live eligibility/DCE gates.','Title-led classifier favors precision over recall.']}
    (out/'route_aware_summary.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')

    md=['# SPM Market Intelligence v8 — Route Aware','','**Two separate commercial motions:** OPEN BID vs DIRECT BUYER. Historical priors only; live eligibility must still be verified.','','## Top OPEN BID lanes','','|#|Source / country|Lane|Open tenders|Buyers|Median award|Median bidders|Single-bid|Repeat buyers|Top supplier|Score|','|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(opens[:30],1): md.append(f"|{i}|{r.get('warehouse_source')} / {r.get('country')}|{r.get('lane')}|{r.get('tender_count')}|{r.get('unique_buyers')}|{r.get('currency')} {r.get('median_award_value') or 'NA'}|{r.get('median_bidder_count') or 'NA'}|{r.get('single_bid_pct') or 'NA'}|{r.get('repeat_buyer_count')}|{r.get('top_supplier_share_pct') or 'NA'}%|{r.get('open_bid_score')}|")
    md+=['','## Top DIRECT BUYER / OUTREACH lanes','','|#|Source / country|Lane|Direct tenders|Buyers|Median award|Repeat buyers|Top supplier|Score|','|---:|---|---|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(directs[:30],1): md.append(f"|{i}|{r.get('warehouse_source')} / {r.get('country')}|{r.get('lane')}|{r.get('tender_count')}|{r.get('unique_buyers')}|{r.get('currency')} {r.get('median_award_value') or 'NA'}|{r.get('repeat_buyer_count')}|{r.get('top_supplier_share_pct') or 'NA'}%|{r.get('direct_buyer_score')}|")
    md+=['','## Deep OPEN BID evidence — top 12','']
    for item in snapshot['open_bid_top30'][:12]:
        r=item['cohort']; md += [f"### {item['rank']}. {r.get('warehouse_source')} / {r.get('country')} — {r.get('lane')}",'',f"- Open-public historical tenders: {r.get('tender_count')}; buyers: {r.get('unique_buyers')}; median award: {r.get('currency')} {r.get('median_award_value')}; median bidders: {r.get('median_bidder_count')}; bidder coverage: {r.get('bidder_coverage_pct')}%; single-bid among observed: {r.get('single_bid_pct')}%; repeat buyers: {r.get('repeat_buyer_count')}; supplier HHI: {r.get('supplier_hhi')}." ]
        if item['route_mix']: md.append('- Full route mix: '+'; '.join(f"{x.get('route_band')}={x.get('tender_count')}" for x in item['route_mix']))
        if item['top_repeat_buyers']: md.append('- Repeat open buyers: '+'; '.join(f"{x.get('buyer_name')} ({x.get('tender_count')})" for x in item['top_repeat_buyers'][:5]))
        if item['top_winners']: md.append('- Top open winners: '+'; '.join(f"{x.get('supplier_name') or x.get('supplier_id')} ({x.get('supplier_share_pct')}%)" for x in item['top_winners'][:5]))
        if item['examples']:
            md.append('- Open examples:')
            for x in item['examples'][:4]: md.append(f"  - {x.get('title')} — {x.get('buyer_name')} — {x.get('currency')} {x.get('award_value') or 'NA'} — bidders {x.get('bidder_count') or 'NA'} — procedure {x.get('procurement_procedure')} — winner(s) {x.get('supplier_names') or 'UNKNOWN'}")
        md.append('')
    md+=['## Deep DIRECT BUYER evidence — top 8','']
    for item in snapshot['direct_buyer_top30'][:8]:
        r=item['cohort']; md += [f"### {item['rank']}. {r.get('warehouse_source')} / {r.get('country')} — {r.get('lane')}",'',f"- Direct/noncompetitive historical tenders: {r.get('tender_count')}; buyers: {r.get('unique_buyers')}; median award: {r.get('currency')} {r.get('median_award_value')}; repeat buyers: {r.get('repeat_buyer_count')}; supplier HHI: {r.get('supplier_hhi')}. **This is outreach evidence, not open-bid competition evidence.**"]
        if item['top_repeat_buyers']: md.append('- Repeat direct buyers: '+'; '.join(f"{x.get('buyer_name')} ({x.get('tender_count')})" for x in item['top_repeat_buyers'][:5]))
        if item['examples']:
            md.append('- Direct examples:')
            for x in item['examples'][:4]: md.append(f"  - {x.get('title')} — {x.get('buyer_name')} — {x.get('currency')} {x.get('award_value') or 'NA'} — procedure {x.get('procurement_procedure')} — supplier {x.get('supplier_names') or 'UNKNOWN'}")
        md.append('')
    md+=['## Guardrails','']+[f'- {g}' for g in snapshot['guardrails']]
    (out/'REPORT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')

    counts={}
    for f in out.glob('*.csv'):
        counts[f.name]=con.execute('SELECT count(*) FROM read_csv_auto(?,header=true,union_by_name=true)',[str(f)]).fetchone()[0]
    manifest={'version':VERSION,'generated_at':snapshot['generated_at'],'outputs':counts,'files':{}}
    for f in out.iterdir():
        if f.is_file():
            b=f.read_bytes();manifest['files'][f.name]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'version':VERSION,'clean_title_tenders':con.execute('select count(*) from tend').fetchone()[0],'outputs':counts,'top_open':[x['cohort'] for x in snapshot['open_bid_top30'][:10]],'top_direct':[x['cohort'] for x in snapshot['direct_buyer_top30'][:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
