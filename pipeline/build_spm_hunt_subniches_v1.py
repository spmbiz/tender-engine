#!/usr/bin/env python3
from __future__ import annotations

"""Strict title-led historical sub-niche intelligence for SPM Business.

Historical/retrieval intelligence only. It never satisfies DCE gates, never
creates GREEN/SUPER_GREEN, never mixes currencies, and fractionalises consortium
award groups when measuring supplier concentration.
"""

import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path
import duckdb

VERSION = "SPM_HUNT_SUBNICHES_V1"


def wcsv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(headers); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--historical',required=True); ap.add_argument('--awards',required=True)
    ap.add_argument('--bridge',required=True); ap.add_argument('--out',required=True)
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(out/'work.duckdb'))
    con.execute("SET preserve_insertion_order=false"); con.execute("SET threads=4"); con.execute("SET memory_limit='10GB'")

    # Canonical Global Core v4 column contract, already QA-validated upstream.
    con.execute("""
      CREATE TABLE h AS SELECT
        trim(cast(Warehouse_Source as varchar)) warehouse_source,
        trim(cast(Historical_Tender_ID as varchar)) tender_id,
        upper(coalesce(nullif(trim(cast(Country as varchar)),''),trim(cast(Warehouse_Source as varchar)))) country,
        lower(regexp_replace(coalesce(nullif(trim(cast(Buyer_ID as varchar)),''),trim(cast(Buyer_Name as varchar))),'\\s+',' ','g')) buyer_key,
        trim(cast(Buyer_Name as varchar)) buyer_name,
        upper(coalesce(nullif(trim(cast(Currency as varchar)),''),'UNKNOWN')) currency,
        try_cast(Official_Estimated_Value as double) estimated_value,
        try_cast(Publication_Date as date) publication_date,
        trim(cast(Title as varchar)) title,
        lower(trim(cast(Title as varchar))) title_l,
        lower(coalesce(trim(cast(Procedure as varchar)),'unknown')) procedure_l,
        trim(cast(Primary_Source_URL as varchar)) official_url
      FROM read_parquet(?)
    """,[a.historical])
    con.execute("""
      CREATE TEMP TABLE aw AS SELECT
        trim(cast(Warehouse_Source as varchar)) warehouse_source,
        trim(cast(Historical_Tender_ID as varchar)) tender_id,
        trim(cast(Award_ID as varchar)) award_id,
        try_cast(Award_Value as double) award_value,
        upper(coalesce(nullif(trim(cast(Currency as varchar)),''),'UNKNOWN')) award_currency,
        try_cast(Bidder_Count as double) bidder_count
      FROM read_parquet(?)
    """,[a.awards])
    con.execute("""
      CREATE TEMP TABLE br AS SELECT
        trim(cast(Warehouse_Source as varchar)) warehouse_source,
        trim(cast(Award_ID as varchar)) award_id,
        trim(cast(Supplier_ID as varchar)) supplier_id,
        trim(cast(Supplier_Name as varchar)) supplier_name
      FROM read_parquet(?) WHERE nullif(trim(cast(Supplier_ID as varchar)),'') IS NOT NULL
    """,[a.bridge])

    con.execute("""
      CREATE TABLE classified AS
      WITH x AS (
        SELECT *,
          CASE
            WHEN lower(warehouse_source)='quebec' THEN CASE
              WHEN procedure_l LIKE '%gré à gré%' THEN 'DIRECT_NONCOMPETITIVE'
              WHEN procedure_l LIKE '%invitation%' THEN 'LIMITED_INVITATION'
              WHEN procedure_l LIKE '%avis d’appel d’offres%' OR procedure_l LIKE '%avis d''appel d''offres%'
                OR procedure_l LIKE '%appel d’offres public%' OR procedure_l LIKE '%appel d''offres public%' THEN 'OPEN_PUBLIC'
              ELSE 'UNKNOWN' END
            WHEN lower(warehouse_source)='canada federal' THEN CASE
              WHEN procedure_l='competitive - open bidding' THEN 'OPEN_PUBLIC'
              WHEN procedure_l IN ('competitive - traditional','competitive - selective tendering','competitive - limited tendering') THEN 'COMPETITIVE_OTHER'
              WHEN procedure_l IN ('advance contract award notice','non-competitive') THEN 'DIRECT_NONCOMPETITIVE'
              ELSE 'UNKNOWN' END
            WHEN lower(warehouse_source)='france' THEN CASE
              WHEN procedure_l LIKE 'ouvert/%' OR procedure_l='ouvert/' THEN 'OPEN_PUBLIC'
              WHEN procedure_l LIKE 'procedure_adapte/%' OR procedure_l='procedure_adapte/' OR procedure_l LIKE 'restreint/%' OR procedure_l='restreint/' OR procedure_l LIKE '%avec_pub_prealable%' OR procedure_l LIKE 'dialogue_competitif/%' THEN 'COMPETITIVE_OTHER'
              WHEN procedure_l LIKE '%sans_pub%' OR procedure_l LIKE 'attribue_sans_pub%' THEN 'DIRECT_NONCOMPETITIVE'
              ELSE 'UNKNOWN' END
            WHEN lower(warehouse_source)='germany' THEN CASE
              WHEN procedure_l IN ('de-open','open','us-open') THEN 'OPEN_PUBLIC'
              WHEN procedure_l IN ('restricted','de-restricted-w-call','neg-w-call','de-comp-w-call','de-comp-neg-w-call','comp-tend','comp-dial','us-neg-w-call','us-res-tw') THEN 'COMPETITIVE_OTHER'
              WHEN procedure_l IN ('neg-wo-call','de-restricted-wo-call','de-comp-wo-call','de-comp-neg-wo-call','oth-single','us-neg-wo-call','us-free-no-tw','us-res-no-tw') THEN 'DIRECT_NONCOMPETITIVE'
              ELSE 'UNKNOWN' END
            ELSE 'UNKNOWN' END route_band,
          CASE
            -- FRANCE PRINT / ROUTING
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(routage|mise sous pli|publipostage|mailing)') THEN 'FR · Mailing / routing / fulfilment'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(journal municipal|magazine municipal|bulletin municipal|journal du département|magazine du département|magazine de la ville|journal de la ville)') AND regexp_matches(title_l,'(impression|imprimer)') THEN 'FR · Municipal/public magazine printing'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(brochure|publication|livret|ouvrage|catalogue|agenda)') AND regexp_matches(title_l,'(impression|imprimer)') THEN 'FR · Brochure / publication / book printing'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(affiche|flyer|dépliant|prospectus|support[s]? de communication)') AND regexp_matches(title_l,'(impression|imprimer)') THEN 'FR · Communication collateral printing'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(papeterie|carte[s]? de visite|formulaire|imprimés administratifs|carnet|enveloppe)') AND regexp_matches(title_l,'(impression|imprimer|fourniture)') THEN 'FR · Forms / stationery / cards printing'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(travaux d.?impression|prestations? d.?impression|services? d.?impression|impression de|impression des)') AND NOT regexp_matches(title_l,'(imprimante|copieur|photocop|système.{0,30}impression|presse numérique|location.{0,40}(copieur|presse)|maintenance.{0,40}(copieur|presse)|transformation.{0,40}imprimerie|3d)') THEN 'FR · General commercial print production'
            -- FRANCE CREATIVE
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(identité visuelle|charte graphique|création de logo|conception de logo)') AND NOT regexp_matches(title_l,'(scénograph|muséograph|architecture|exposition)') THEN 'FR · Visual identity / branding'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(mise en page|\\bpao\\b|desktop publishing|infographie)') AND regexp_matches(title_l,'(magazine|journal|publication|rapport|ouvrage|document|brochure|livret)') AND NOT regexp_matches(title_l,'(scénograph|muséograph|architecture|exposition)') THEN 'FR · Publication layout / DTP'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(conception graphique|création graphique|design graphique|graphisme)') AND NOT regexp_matches(title_l,'(scénograph|muséograph|architecture|exposition|stand|travaux)') THEN 'FR · General graphic design'
            -- FRANCE LANGUAGE
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(sténotyp|sténograph)') THEN 'FR · Stenotypy / stenography'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(transcription|retranscription)') AND NOT regexp_matches(title_l,'(adn|dna|gène|gene|facteur de transcription)') THEN 'FR · Meeting / debate transcription'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(interprétariat|interprétation)') AND NOT regexp_matches(title_l,'(matériel|équipement|audiovisuel|location)') THEN 'FR · Human interpreting'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'traduction') AND NOT regexp_matches(title_l,'(matériel|équipement|audiovisuel|location|translationnelle|médecine)') THEN 'FR · Written translation'
            -- FRANCE WEB
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(rgaa|wcag|accessibilité)') AND regexp_matches(title_l,'(site web|site internet|website|portail web)') THEN 'FR · Web accessibility / RGAA-WCAG'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(wordpress|drupal|joomla)') AND regexp_matches(title_l,'(site|website|cms|portail)') THEN 'FR · Drupal / WordPress / CMS implementation'
            WHEN lower(warehouse_source)='france' AND (regexp_matches(title_l,'(site web|site internet|website|portail web).{0,90}(maintenance|support|hébergement|entretien|mise à jour)') OR regexp_matches(title_l,'(maintenance|support|hébergement|entretien|mise à jour).{0,90}(site web|site internet|website|portail web)')) THEN 'FR · Website maintenance / hosting / support'
            WHEN lower(warehouse_source)='france' AND (regexp_matches(title_l,'(refonte|création|conception|développement|redesign|relaunch).{0,90}(site web|site internet|website|portail web)') OR regexp_matches(title_l,'(site web|site internet|website|portail web).{0,90}(refonte|création|conception|développement|redesign|relaunch)')) AND NOT regexp_matches(title_l,'(construction|hardware|matériel)') THEN 'FR · Website redesign / development'
            -- GERMANY WEB
            WHEN lower(warehouse_source)='germany' AND regexp_matches(title_l,'(barrierefrei|barrierefreiheit)') AND regexp_matches(title_l,'(website|webseite|internetauftritt|webauftritt)') THEN 'DE · Web accessibility / Barrierefreiheit'
            WHEN lower(warehouse_source)='germany' AND regexp_matches(title_l,'(typo3|wordpress|drupal|joomla)') AND regexp_matches(title_l,'(website|webseite|cms|portal|internetauftritt)') THEN 'DE · TYPO3 / Drupal / WordPress CMS'
            WHEN lower(warehouse_source)='germany' AND (regexp_matches(title_l,'(website|webseite|internetauftritt|webauftritt).{0,90}(pflege|wartung|betreuung|support)') OR regexp_matches(title_l,'(pflege|wartung|betreuung|support).{0,90}(website|webseite|internetauftritt|webauftritt)')) THEN 'DE · Website maintenance / support'
            WHEN lower(warehouse_source)='germany' AND (regexp_matches(title_l,'(website|webseite|internetauftritt|webauftritt).{0,90}(hosting|betrieb)') OR regexp_matches(title_l,'(hosting|betrieb).{0,90}(website|webseite|internetauftritt|webauftritt)')) THEN 'DE · Website hosting / operation'
            WHEN lower(warehouse_source)='germany' AND (regexp_matches(title_l,'(relaunch|neugestaltung|entwicklung|redesign).{0,90}(website|webseite|internetauftritt|webportal)') OR regexp_matches(title_l,'(website|webseite|internetauftritt|webportal).{0,90}(relaunch|neugestaltung|entwicklung|redesign)')) THEN 'DE · Website relaunch / development'
            -- QUEBEC PRINT
            WHEN lower(warehouse_source)='quebec' AND regexp_matches(title_l,'(grand format|affichage)') AND regexp_matches(title_l,'impression') THEN 'QC · Large-format / display printing'
            WHEN lower(warehouse_source)='quebec' AND regexp_matches(title_l,'(recueil|notes de cours|manuel|cahier|matériel pédagogique)') AND regexp_matches(title_l,'impression') THEN 'QC · Educational / course-material printing'
            WHEN lower(warehouse_source)='quebec' AND regexp_matches(title_l,'(brochure|publication|livret|catalogue|agenda)') AND regexp_matches(title_l,'impression') THEN 'QC · Brochure / publication printing'
            WHEN lower(warehouse_source)='quebec' AND regexp_matches(title_l,'(vignette|permis|carte|papeterie|formulaire|papier filigrané)') AND regexp_matches(title_l,'(impression|imprimé)') THEN 'QC · Permits / forms / stationery printing'
            WHEN lower(warehouse_source)='quebec' AND regexp_matches(title_l,'(services? d.?impression|travaux d.?impression|impression de|impression des)') AND NOT regexp_matches(title_l,'(imprimante|copieur|photocop|3d|maintenance.{0,30}(imprimante|copieur)|location.{0,30}(imprimante|copieur))') THEN 'QC · General commercial print production'
            -- CANADA FEDERAL LANGUAGE
            WHEN lower(warehouse_source)='canada federal' AND regexp_matches(title_l,'(asl|lsq|sign language|interpretation services?|interpreting)') AND NOT regexp_matches(title_l,'(equipment|hardware|audio visual|audiovisual)') THEN 'CA · Interpretation / sign-language services'
            WHEN lower(warehouse_source)='canada federal' AND regexp_matches(title_l,'(technical translation|professional translation|translation services?|english to french|french to english)') AND NOT regexp_matches(title_l,'(equipment|hardware|translational)') THEN 'CA · Written translation'
            -- FRANCE PROMOTIONAL BROKER WATCH
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(textile|t-shirt|tee-shirt|vêtement|habillement)') AND regexp_matches(title_l,'(promotionnel|publicitaire|marquage|personnalis)') THEN 'FR · Branded textiles / apparel'
            WHEN lower(warehouse_source)='france' AND regexp_matches(title_l,'(objets publicitaires|articles promotionnels|goodies|objets promotionnels|cadeaux publicitaires)') THEN 'FR · Promotional objects / branded goods'
            ELSE NULL END sub_niche
        FROM h
      )
      SELECT *, CASE
        WHEN sub_niche LIKE 'FR · %printing%' OR sub_niche LIKE 'QC · %printing%' OR sub_niche LIKE 'FR · Mailing%' THEN 'PRINT_BROKER'
        WHEN sub_niche LIKE 'FR · %graphic%' OR sub_niche LIKE 'FR · Visual%' OR sub_niche LIKE 'FR · Publication layout%' THEN 'CREATIVE'
        WHEN sub_niche LIKE 'FR · %translation%' OR sub_niche LIKE 'FR · Human interpreting%' OR sub_niche LIKE 'FR · %transcription%' OR sub_niche LIKE 'FR · Stenotypy%' OR sub_niche LIKE 'CA · %' THEN 'LANGUAGE'
        WHEN sub_niche LIKE 'FR · Website%' OR sub_niche LIKE 'FR · Web accessibility%' OR sub_niche LIKE 'FR · Drupal%' OR sub_niche LIKE 'DE · %' THEN 'WEB_DIGITAL'
        WHEN sub_niche LIKE 'FR · Branded%' OR sub_niche LIKE 'FR · Promotional%' THEN 'PROMO_BROKER'
        ELSE 'OTHER' END parent_lane
      FROM x WHERE sub_niche IS NOT NULL
    """)

    con.execute("""
      CREATE TEMP TABLE awt AS SELECT warehouse_source,tender_id,
        median(bidder_count) FILTER(WHERE bidder_count IS NOT NULL AND bidder_count>=0) median_bidders,
        count(*) FILTER(WHERE bidder_count IS NOT NULL AND bidder_count>=0) bidder_rows,
        count(*) FILTER(WHERE bidder_count=1) one_bid_rows
      FROM aw GROUP BY 1,2
    """)
    con.execute("""
      CREATE TEMP TABLE repeat_buyers AS SELECT sub_niche,parent_lane,warehouse_source,country,route_band,currency,buyer_key,
        max(buyer_name) buyer_name,count(*) procurements,min(publication_date) first_date,max(publication_date) last_date,
        median(estimated_value) FILTER(WHERE estimated_value>0) median_estimated_value
      FROM classified WHERE buyer_key<>'' GROUP BY 1,2,3,4,5,6,7 HAVING count(*)>=2
    """)
    con.execute("CREATE TEMP TABLE brc AS SELECT warehouse_source,award_id,count(*) n FROM br GROUP BY 1,2")
    con.execute("""
      CREATE TEMP TABLE sw AS SELECT t.sub_niche,t.parent_lane,t.warehouse_source,t.country,t.route_band,t.currency,
        b.supplier_id,max(b.supplier_name) supplier_name,sum(1.0/nullif(c.n,0)) fractional_awards
      FROM classified t JOIN aw a USING(warehouse_source,tender_id) JOIN br b USING(warehouse_source,award_id) JOIN brc c USING(warehouse_source,award_id)
      GROUP BY 1,2,3,4,5,6,7
    """)
    con.execute("""
      CREATE TEMP TABLE ss AS WITH x AS (
        SELECT *,sum(fractional_awards) OVER(PARTITION BY sub_niche,warehouse_source,country,route_band,currency) tw FROM sw)
      SELECT sub_niche,warehouse_source,country,route_band,currency,count(*) supplier_count,
        max(fractional_awards/nullif(tw,0)) top_supplier_share,sum(power(100.0*fractional_awards/nullif(tw,0),2)) hhi
      FROM x GROUP BY 1,2,3,4,5
    """)
    con.execute("""
      CREATE TABLE cohort AS WITH base AS (
        SELECT t.sub_niche,t.parent_lane,t.warehouse_source,t.country,t.route_band,t.currency,count(*) records,
          count(DISTINCT nullif(t.buyer_key,'')) buyers,median(t.estimated_value) FILTER(WHERE t.estimated_value>0) median_estimated_value,
          median(awt.median_bidders) FILTER(WHERE awt.bidder_rows>0) median_bidders,sum(coalesce(awt.bidder_rows,0)) bidder_rows,
          sum(coalesce(awt.one_bid_rows,0)) one_bid_rows
        FROM classified t LEFT JOIN awt USING(warehouse_source,tender_id) GROUP BY 1,2,3,4,5,6),
      av AS (
        SELECT t.sub_niche,t.warehouse_source,t.country,t.route_band,t.currency,
          count(*) FILTER(WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) award_value_rows,
          quantile_cont(a.award_value,.25) FILTER(WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) p25_award_value,
          median(a.award_value) FILTER(WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) median_award_value,
          quantile_cont(a.award_value,.75) FILTER(WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) p75_award_value
        FROM classified t LEFT JOIN aw a USING(warehouse_source,tender_id) GROUP BY 1,2,3,4,5),
      rb AS (
        SELECT sub_niche,warehouse_source,country,route_band,currency,count(*) repeat_buyers,sum(procurements) repeat_procurements
        FROM repeat_buyers GROUP BY 1,2,3,4,5)
      SELECT b.*,a.award_value_rows,a.p25_award_value,a.median_award_value,a.p75_award_value,
        coalesce(r.repeat_buyers,0) repeat_buyers,coalesce(r.repeat_procurements,0) repeat_procurements,
        CASE WHEN b.buyers>0 THEN 1.0*coalesce(r.repeat_buyers,0)/b.buyers ELSE 0 END repeat_buyer_rate,
        CASE WHEN b.bidder_rows>0 THEN 1.0*b.one_bid_rows/b.bidder_rows ELSE NULL END single_bid_rate,
        s.supplier_count,s.top_supplier_share,s.hhi
      FROM base b JOIN av a USING(sub_niche,warehouse_source,country,route_band,currency)
      LEFT JOIN rb r USING(sub_niche,warehouse_source,country,route_band,currency)
      LEFT JOIN ss s USING(sub_niche,warehouse_source,country,route_band,currency)
    """)
    con.execute("""
      CREATE TABLE ranked AS WITH x AS (
        SELECT *,
          CASE parent_lane WHEN 'WEB_DIGITAL' THEN 5.0 WHEN 'CREATIVE' THEN 5.0 WHEN 'LANGUAGE' THEN 4.5 WHEN 'PRINT_BROKER' THEN 2.0 WHEN 'PROMO_BROKER' THEN 1.5 ELSE 2.5 END ai_leverage,
          CASE parent_lane WHEN 'PRINT_BROKER' THEN 5.0 WHEN 'PROMO_BROKER' THEN 5.0 WHEN 'LANGUAGE' THEN 4.0 WHEN 'CREATIVE' THEN 3.5 WHEN 'WEB_DIGITAL' THEN 3.0 ELSE 2.5 END subcontractability,
          CASE WHEN sub_niche LIKE '%Stenotypy%' THEN 4.5 WHEN sub_niche LIKE '%Human interpreting%' OR sub_niche LIKE '%sign-language%' THEN 4.0 WHEN parent_lane='PROMO_BROKER' THEN 3.5 WHEN parent_lane='PRINT_BROKER' THEN 3.0 WHEN parent_lane='WEB_DIGITAL' THEN 2.5 ELSE 2.0 END delivery_gate_risk,
          CASE WHEN parent_lane IN ('PRINT_BROKER','PROMO_BROKER') THEN 4.0 WHEN parent_lane='LANGUAGE' THEN 1.5 ELSE 1.0 END working_capital_risk,
          CASE WHEN median_award_value IS NULL THEN 3.0 WHEN median_award_value<10000 THEN 2.0 WHEN median_award_value<=500000 THEN 5.0 WHEN median_award_value<=1500000 THEN 4.0 WHEN median_award_value<=5000000 THEN 2.5 ELSE 1.5 END ticket_fit,
          CASE WHEN bidder_rows>=10 AND median_bidders IS NOT NULL THEN greatest(1.0,least(5.0,6.0-median_bidders/1.5)) ELSE 3.0 END competition_fit,
          greatest(1.0,least(5.0,1.0+12.0*repeat_buyer_rate)) recurrence_fit,
          CASE WHEN supplier_count>=5 AND top_supplier_share IS NOT NULL THEN greatest(1.0,least(5.0,5.5-10.0*top_supplier_share)) ELSE 3.0 END fragmentation_fit,
          percent_rank() OVER(ORDER BY records) volume_pct,percent_rank() OVER(ORDER BY buyers) buyer_pct
        FROM cohort WHERE records>=3)
      SELECT *,round(100.0*(.12*volume_pct+.10*buyer_pct+.14*(ai_leverage/5.0)+.12*(subcontractability/5.0)+.13*(ticket_fit/5.0)+.12*(competition_fit/5.0)+.10*(recurrence_fit/5.0)+.08*(fragmentation_fit/5.0)+.05*(1.0-delivery_gate_risk/5.0)+.04*(1.0-working_capital_risk/5.0)),2) spm_hunt_score,
        CASE WHEN route_band IN ('OPEN_PUBLIC','COMPETITIVE_OTHER') THEN 'OPEN_HUNT' WHEN route_band='DIRECT_NONCOMPETITIVE' THEN 'DIRECT_BUYER_INTEL' ELSE 'OTHER_ROUTE' END market_motion
      FROM x
    """)

    hdr=['sub_niche','parent_lane','warehouse_source','country','route','currency','records','buyers','repeat_buyers','repeat_buyer_rate_pct','median_estimated_value','award_value_rows','p25_award_value','median_award_value','p75_award_value','bidder_rows','median_bidders','single_bid_pct','supplier_count','top_supplier_share_pct','hhi','ai_leverage_1_5','subcontractability_1_5','delivery_gate_risk_1_5','working_capital_risk_1_5','ticket_fit_1_5','competition_fit_1_5','recurrence_fit_1_5','fragmentation_fit_1_5','spm_hunt_score','market_motion']
    sel="""SELECT sub_niche,parent_lane,warehouse_source,country,route_band,currency,records,buyers,repeat_buyers,round(100*repeat_buyer_rate,2),median_estimated_value,award_value_rows,p25_award_value,median_award_value,p75_award_value,bidder_rows,median_bidders,round(100*single_bid_rate,2),supplier_count,round(100*top_supplier_share,2),round(hhi,2),ai_leverage,subcontractability,delivery_gate_risk,working_capital_risk,ticket_fit,competition_fit,recurrence_fit,fragmentation_fit,spm_hunt_score,market_motion FROM ranked"""
    wcsv(out/'subniche_rank.csv',hdr,con.execute(sel+" ORDER BY spm_hunt_score DESC,records DESC").fetchall())
    wcsv(out/'open_hunt_subniches.csv',hdr,con.execute(sel+" WHERE market_motion='OPEN_HUNT' ORDER BY spm_hunt_score DESC,records DESC").fetchall())
    wcsv(out/'direct_buyer_subniches.csv',hdr,con.execute(sel+" WHERE market_motion='DIRECT_BUYER_INTEL' ORDER BY spm_hunt_score DESC,records DESC").fetchall())

    wcsv(out/'repeat_buyers_subniche.csv',['sub_niche','parent_lane','warehouse_source','country','route','currency','buyer','procurements','first_date','last_date','median_estimated_value'],con.execute("""SELECT sub_niche,parent_lane,warehouse_source,country,route_band,currency,buyer_name,procurements,first_date,last_date,median_estimated_value FROM repeat_buyers ORDER BY procurements DESC,sub_niche LIMIT 10000""").fetchall())
    wcsv(out/'top_winners_subniche.csv',['sub_niche','parent_lane','warehouse_source','country','route','currency','supplier','fractional_awards','share_pct'],con.execute("""WITH x AS (SELECT *,sum(fractional_awards) OVER(PARTITION BY sub_niche,warehouse_source,country,route_band,currency) tw,row_number() OVER(PARTITION BY sub_niche,warehouse_source,country,route_band,currency ORDER BY fractional_awards DESC,supplier_id) rn FROM sw) SELECT sub_niche,parent_lane,warehouse_source,country,route_band,currency,supplier_name,round(fractional_awards,3),round(100*fractional_awards/nullif(tw,0),2) FROM x WHERE rn<=10 ORDER BY sub_niche,warehouse_source,country,route_band,currency,rn""").fetchall())
    wcsv(out/'representative_examples_subniche.csv',['sub_niche','parent_lane','warehouse_source','country','route','currency','buyer','title','estimated_value','publication_date','url'],con.execute("""WITH z AS (SELECT *,row_number() OVER(PARTITION BY sub_niche,warehouse_source,country,route_band ORDER BY hash(tender_id,title)) rn FROM classified) SELECT sub_niche,parent_lane,warehouse_source,country,route_band,currency,buyer_name,title,estimated_value,publication_date,official_url FROM z WHERE rn<=8 ORDER BY sub_niche,warehouse_source,country,route_band,rn""").fetchall())

    top=con.execute("""SELECT sub_niche,parent_lane,country,route_band,currency,records,buyers,repeat_buyers,median_award_value,median_bidders,round(100*top_supplier_share,2),spm_hunt_score FROM ranked WHERE market_motion='OPEN_HUNT' ORDER BY spm_hunt_score DESC,records DESC LIMIT 40""").fetchall()
    def model(parent,sub):
        if parent=='PRINT_BROKER': return ('HUNT_LIVE_BROKER','SPM prime + print subcontractor; normalize specs/quotes; margin on production/logistics','paper/finish/quantity; proofs; delivery/routing; eco labels; locality; subcontracting; working capital; penalties')
        if parent=='PROMO_BROKER': return ('WATCH_AND_BROKER','SPM prime + merchandise/textile supplier','samples; certifications; eco/textile labels; personalization; delivery; stock; reseller/manufacturer constraints; working capital')
        if parent=='WEB_DIGITAL': return ('HUNT_LIVE_CORE','SPM-led AI/code implementation; specialist only for audited accessibility/security/on-site constraints','references; CMS stack; hosting/security; accessibility; SLA; GDPR; IP/source code; on-site; turnover/insurance')
        if parent=='CREATIVE': return ('HUNT_LIVE_CORE','SPM AI/creative production + human art direction/QA','portfolio references; editable/source files; brand constraints; print bundle; accessibility; meetings/on-site; IP; staffing')
        if parent=='LANGUAGE':
            if 'Stenotypy' in sub or 'interpreting' in sub.lower() or 'sign-language' in sub.lower(): return ('HUNT_ONLY_IF_STAFFABLE','AI assists, but qualified human/on-site professional may be mandatory','named staff; qualifications; on-site; confidentiality; clearance; turnaround; accuracy; language pairs')
            return ('HUNT_LIVE_AI_HUMAN','AI-first draft/transcription + professional human QA','certified-human requirement; language pairs; confidentiality; security; CAT/TM ownership; accuracy; turnaround; references')
        return ('WATCH','Case-by-case','DCE mandatory')
    ph=['rank','sub_niche','country','route','currency','records','buyers','repeat_buyers','median_award_value','median_bidders','top_supplier_share_pct','spm_hunt_score','recommended_motion','fulfilment_model','main_live_dce_checks']
    prows=[]
    for i,r in enumerate(top,1):
        sub,parent,country,route,cur,recs,buyers,rep,med,mbid,share,score=r; motion,fulfil,checks=model(parent,sub)
        prows.append([i,sub,country,route,cur,recs,buyers,rep,med,mbid,share,score,motion,fulfil,checks])
    wcsv(out/'hunt_playbook.csv',ph,prows)

    counts=con.execute("SELECT count(*),count(DISTINCT tender_id),count(DISTINCT sub_niche),count(DISTINCT nullif(buyer_key,'')) FROM classified").fetchone()
    openc=con.execute("SELECT count(*) FROM classified WHERE route_band IN ('OPEN_PUBLIC','COMPETITIVE_OTHER')").fetchone()[0]
    directc=con.execute("SELECT count(*) FROM classified WHERE route_band='DIRECT_NONCOMPETITIVE'").fetchone()[0]
    lines=['# SPM Hunt Sub-Niches v1','',f'Version: `{VERSION}`','',f'Strict title-led classified tenders: **{counts[0]:,}** across **{counts[2]}** concrete sub-niches and **{counts[3]:,}** buyers.',f'Open/competitive route rows: **{openc:,}**. Direct-buyer rows: **{directc:,}**.','','Historical market/retrieval intelligence only. No DCE gate is satisfied by this analysis.','','## Top open-hunt sub-niches','','|#|Sub-niche|Country|Records|Buyers|Repeat buyers|Median award|Median bidders|Top supplier share|Hunt score|','|---:|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in prows[:25]:
        _,sub,country,route,cur,recs,buyers,rep,med,mbid,share,score,*_=row
        lines.append(f"|{row[0]}|{sub}|{country}|{recs}|{buyers}|{rep}|{'UNKNOWN' if med is None else cur+' '+format(med,'.2f')}|{'UNKNOWN' if mbid is None else format(mbid,'.2f')}|{'UNKNOWN' if share is None else format(share,'.2f')+'%'}|{score:.2f}|")
    lines += ['','## Guardrails','','- `spm_hunt_score` mixes observed historical market structure with explicit SPM execution priors; it is not a win-probability estimate.','- Monetary cohorts are currency-isolated; no FX normalization is performed.','- Missing bidder evidence remains UNKNOWN.','- Consortium awards are fractionalised across suppliers for concentration statistics.','- OPEN_HUNT means prioritize live discovery/DCE retrieval, never bid automatically.','- DIRECT_BUYER_INTEL is demand/outbound intelligence only.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    manifest={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'source_grain':'GLOBAL_CORE_V4_NOTICE_FIRST','counts':{'classified_records':counts[0],'distinct_tenders':counts[1],'sub_niches':counts[2],'buyers':counts[3],'open_or_competitive_rows':openc,'direct_noncompetitive_rows':directc},'safety':{'historical_only':True,'satisfies_dce_gates':False,'affects_final_verdict':False,'no_fx_mixing':True,'consortium_award_fractionalized':True,'unknown_is_not_zero':True,'title_led_classifier':True},'business_heuristics':{'ai_leverage':'1-5 SPM prior, not observed fact','subcontractability':'1-5 SPM prior, not observed fact','delivery_gate_risk':'1-5 SPM prior, higher is harder','working_capital_risk':'1-5 SPM prior, higher is harder','spm_hunt_score':'retrieval/business-priority heuristic only'}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); print(json.dumps(manifest,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
