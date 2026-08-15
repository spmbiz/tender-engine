#!/usr/bin/env python3
from __future__ import annotations

"""Full-corpus micro-niche procurement intelligence for SPM Business.

Reads canonical Global Core v4 NOTICE_FIRST_TENDER facts plus awards and
award↔supplier links. Produces currency-isolated, route-aware micro-niche
statistics, repeat-buyer evidence, winner concentration and representative
historical examples.

This is historical intelligence only. It never satisfies live DCE gates and
never creates a final GREEN/SUPER_GREEN verdict.
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

VERSION = "SPM_MICRO_NICHE_INTELLIGENCE_V1"


def qi(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def choose(cols: set[str], *names: str) -> str | None:
    m = {c.casefold(): c for c in cols}
    for n in names:
        if n.casefold() in m:
            return m[n.casefold()]
    return None


def txt(c: str | None, default: str = "''") -> str:
    return f"trim(cast({qi(c)} as varchar))" if c else default


def write_csv(path: Path, headers: list[str], rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical", required=True)
    ap.add_argument("--awards", required=True)
    ap.add_argument("--bridge", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(out / "work.duckdb"))
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")

    hc = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [a.historical]).fetchall()}
    ac = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [a.awards]).fetchall()}
    bc = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [a.bridge]).fetchall()}

    hs = choose(hc, "Warehouse_Source")
    hid = choose(hc, "Historical_Tender_ID")
    hcountry = choose(hc, "Country")
    hbuyer = choose(hc, "Buyer_Name")
    hbuyerid = choose(hc, "Buyer_ID")
    hcur = choose(hc, "Currency")
    hest = choose(hc, "Official_Estimated_Value")
    hpub = choose(hc, "Publication_Date")
    htitle = choose(hc, "Title")
    hscope = choose(hc, "Scope_Summary")
    hcpv = choose(hc, "CPV_NAICS_or_Local_Code")
    hcpvd = choose(hc, "Raw_CPV_Description")
    hproc = choose(hc, "Procedure", "Procedure_Type", "Competition_Type")
    hurl = choose(hc, "Primary_Source_URL")

    aas = choose(ac, "Warehouse_Source")
    aat = choose(ac, "Historical_Tender_ID")
    aid = choose(ac, "Award_ID")
    aval = choose(ac, "Award_Value")
    acur = choose(ac, "Currency")
    abid = choose(ac, "Bidder_Count")

    bs = choose(bc, "Warehouse_Source")
    ba = choose(bc, "Award_ID")
    bsi = choose(bc, "Supplier_ID")
    bsn = choose(bc, "Supplier_Name")

    required = {
        "historical.source": hs, "historical.id": hid, "historical.title": htitle,
        "awards.source": aas, "awards.tender": aat, "awards.id": aid,
        "bridge.source": bs, "bridge.award": ba, "bridge.supplier": bsi,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SystemExit(json.dumps({"missing": missing, "historical_cols": sorted(hc), "award_cols": sorted(ac), "bridge_cols": sorted(bc)}, indent=2))

    source = txt(hs)
    tid = txt(hid)
    country = f"upper(coalesce(nullif({txt(hcountry)},''),{source}))"
    buyer_name = txt(hbuyer)
    buyer_id = txt(hbuyerid)
    buyer_key = f"lower(regexp_replace(coalesce(nullif({buyer_id},''),{buyer_name}),'\\s+',' ','g'))"
    currency = f"upper(coalesce(nullif({txt(hcur)},''),'UNKNOWN'))"
    est = f"try_cast({qi(hest)} as double)" if hest else "NULL::DOUBLE"
    pub = f"try_cast({qi(hpub)} as date)" if hpub else "NULL::DATE"
    title = txt(htitle)
    scope = txt(hscope)
    cpv = txt(hcpv)
    cpvd = txt(hcpvd)
    proc = txt(hproc, "'UNKNOWN'")
    url = txt(hurl)
    text = f"lower(concat_ws(' ',{title},{scope},{cpvd}))"
    title_l = f"lower({title})"

    asrc = txt(aas)
    atid = txt(aat)
    award_id = txt(aid)
    award_value = f"try_cast({qi(aval)} as double)" if aval else "NULL::DOUBLE"
    award_currency = f"upper(coalesce(nullif({txt(acur)},''),'UNKNOWN'))" if acur else "'UNKNOWN'"
    bidders = f"try_cast({qi(abid)} as double)" if abid else "NULL::DOUBLE"

    bsrc = txt(bs)
    baid = txt(ba)
    supplier_id = txt(bsi)
    supplier_name = txt(bsn)

    # High-precision, commercially distinct micro-niches. Priority matters: the
    # most specific classifier wins before a broader parent lane can capture it.
    micro = f"""
    CASE
      WHEN regexp_matches({text}, '(wcag|web accessibility|website accessibility|accessibilit[eé].{0,40}(web|site|num[eé]rique)|barrierefrei.{0,40}(web|internet|website)|accessibility audit)')
        THEN 'Web accessibility / WCAG audit-remediation'
      WHEN regexp_matches({text}, '(wordpress|drupal|joomla)') AND regexp_matches({text}, '(website|web site|site web|site internet|cms|content management)')
        THEN 'WordPress / Drupal / CMS implementation'
      WHEN regexp_matches({text}, '(website|web site|site web|site internet|internetauftritt|webseite|web portal|portail web)') AND regexp_matches({text}, '(maintenance|support|hosting|h[eé]bergement|pflege|betrieb|entretien|mise [àa] jour)')
        THEN 'Website maintenance / hosting / support'
      WHEN regexp_matches({text}, '(website|web site|site web|site internet|internetauftritt|webseite|web portal|portail web)') AND regexp_matches({text}, '(design|redesign|refonte|development|d[eé]veloppement|creation|cr[eé]ation|build|rebuild)')
        THEN 'Website design / redesign / development'

      WHEN regexp_matches({text}, '(annual report|rapport annuel|activity report|rapport d.activit[eé]|publication)') AND regexp_matches({text}, '(layout|mise en page|graphic design|conception graphique|desktop publishing|publishing|production)')
        THEN 'Annual report / publication layout-production'
      WHEN regexp_matches({text}, '(graphic design|conception graphique|design graphique|graphisme|mise en page|desktop publishing|infograph|visual identity|identit[eé] visuelle|grafikdesign|grafische gestaltung)')
           AND NOT regexp_matches({text}, '(architect|engineering|construction|ma[iî]trise d.oeuvre)')
        THEN 'Graphic design / DTP / visual identity'
      WHEN regexp_matches({text}, '(video editing|video edit|montage vid[eé]o|post[- ]production|motion graphics?|motion design|video production|production vid[eé]o|videoproduktion)')
        THEN 'Video production / editing / motion'

      WHEN regexp_matches({text}, '(subtitl|sous[- ]titr|captioning|closed caption)')
        THEN 'Subtitling / captioning'
      WHEN regexp_matches({text}, '(transcription|transcribing|speech[- ]to[- ]text|st[eé]nograph|stenograph)')
        THEN 'Transcription / speech-to-text'
      WHEN regexp_matches({text}, '(translation services?|traduction|übersetz|uebersetz|traducci[oó]n|traduzione|t[łl]umacz)')
           AND NOT regexp_matches({text}, '(translational medicine|translationale medizin|translationnelle)')
        THEN 'Translation services'

      WHEN regexp_matches({text}, '(document scanning|scanning of documents|scan of documents|num[eé]risation.{0,50}(document|archive|dossier|papier)|digitization.{0,50}(document|archive|record)|digitisation.{0,50}(document|archive|record)|\\bocr\\b)')
           AND NOT regexp_matches({text}, '(microscope|medical scanner|laser scanning|lidar|street|road|voirie)')
        THEN 'Document scanning / digitization / OCR'
      WHEN regexp_matches({text}, '(document indexing|metadata creation|records indexing|data entry|saisie de donn[eé]es|clerical processing|document coding)')
        THEN 'Data entry / document indexing'

      WHEN regexp_matches({text}, '(social media management|community management|gestion des r[eé]seaux sociaux|gestion des m[eé]dias sociaux)')
        THEN 'Social media / community management'
      WHEN regexp_matches({text}, '(search engine optimi|\\bseo\\b|r[eé]f[eé]rencement naturel|digital marketing|marketing digital|online marketing)')
        THEN 'SEO / digital marketing'
      WHEN regexp_matches({text}, '(media monitoring|press monitoring|veille m[eé]diatique|revue de presse|medienbeobachtung)')
        THEN 'Media / press monitoring'
      WHEN regexp_matches({text}, '(market research|[eé]tude de march[eé]|opinion poll|customer survey|survey services|sondage)')
           AND NOT regexp_matches({text}, '(geotech|g[eé]otech|soil|drilling|borehole|sondage de sol)')
        THEN 'Market research / surveys / polling'

      WHEN regexp_matches({text}, '(mise sous pli|mailing services|mail fulfilment|mail fulfillment|routage|impression et routage|printing and mailing)')
        THEN 'Mailing / fulfilment / routing'
      WHEN regexp_matches({text}, '(printing services|print production|services d.impression|travaux d.impression|imprimerie|printing and delivery|impression de)')
           AND NOT regexp_matches({text}, '(3d print|printer maintenance|managed print|photocopier|imprimante)')
        THEN 'Commercial printing / print production'
      WHEN regexp_matches({text}, '(promotional merchandise|promotional items|objets publicitaires|articles promotionnels|branded merchandise|corporate gifts|goodies)')
        THEN 'Promotional merchandise / branded goods'

      WHEN regexp_matches({title_l}, '(software licen[cs](e|es|ing)|licen[cs]e renewal|software subscription renewal|licence(s)? logiciel(le)?s?|licences logicielles)')
           AND NOT regexp_matches({text}, '(custom software development|application development|system integration|implementation project)')
        THEN 'Software licence renewal / licensing'
      WHEN regexp_matches({title_l}, '(saas subscription|software subscription|cloud software subscription|subscription software)')
        THEN 'SaaS / cloud software subscription'
      WHEN regexp_matches({text}, '(document management software|document management system|electronic document management|edms|dms software)') AND regexp_matches({text}, '(licen[cs]|subscription|software)')
        THEN 'Document-management software licensing'
      WHEN regexp_matches({text}, '(learning management system|learning platform|moodle|e[- ]learning platform)') AND regexp_matches({text}, '(software|licen[cs]|subscription|hosting|platform)')
        THEN 'LMS / e-learning platform software'
      ELSE NULL
    END
    """

    sl = f"lower(coalesce({source},''))"
    pl = f"lower(coalesce({proc},''))"
    route = f"""
    CASE
      WHEN {sl}='quebec' THEN CASE
        WHEN {pl} LIKE '%gré à gré%' THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%invitation%' THEN 'LIMITED_INVITATION'
        WHEN {pl} LIKE '%avis d’appel d’offres%' OR {pl} LIKE '%avis d''appel d''offres%' OR {pl} LIKE '%appel d’offres public%' OR {pl} LIKE '%appel d''offres public%' THEN 'OPEN_PUBLIC'
        ELSE 'UNKNOWN' END
      WHEN {sl}='canada federal' THEN CASE
        WHEN {pl}='competitive - open bidding' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('competitive - traditional','competitive - selective tendering','competitive - limited tendering') THEN 'COMPETITIVE_OTHER'
        WHEN {pl}='advance contract award notice' OR {pl}='non-competitive' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='france' THEN CASE
        WHEN {pl} LIKE 'ouvert/%' OR {pl}='ouvert/' THEN 'OPEN_PUBLIC'
        WHEN {pl} LIKE 'procedure_adapte/%' OR {pl}='procedure_adapte/' OR {pl} LIKE 'restreint/%' OR {pl}='restreint/' OR {pl} LIKE '%avec_pub_prealable%' OR {pl} LIKE 'dialogue_competitif/%' THEN 'COMPETITIVE_OTHER'
        WHEN {pl} LIKE '%sans_pub%' OR {pl} LIKE 'attribue_sans_pub%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='germany' THEN CASE
        WHEN {pl} IN ('de-open','open','us-open') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted','de-restricted-w-call','neg-w-call','de-comp-w-call','de-comp-neg-w-call','comp-tend','comp-dial','us-neg-w-call','us-res-tw') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('neg-wo-call','de-restricted-wo-call','de-comp-wo-call','de-comp-neg-wo-call','oth-single','us-neg-wo-call','us-free-no-tw','us-res-no-tw') THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='ireland' THEN CASE
        WHEN {pl}='open procedure' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','competitive procedure with negotiation','simplified','competitive dialogue') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('direct invite – mini-competition','dps qualification','uqs qualification') THEN 'FRAMEWORK_DPS_CALLOFF'
        WHEN {pl} IN ('negotiated procedure without prior publication','direct invite – quick quote') THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='united kingdom' THEN CASE
        WHEN {pl} IN ('open procedure','below threshold - open competition','competitive flexible procedure','competitive tendering procedure') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','restricted','below threshold - limited competition','negotiated procedure with prior call for competition','competitive procedure with negotiation','competitive dialogue','negotiated with publication of a contract notice') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('below threshold - without competition','direct award','negotiated without publication of a contract notice') THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%framework%' OR {pl} LIKE '%dynamic market%' THEN 'FRAMEWORK_DPS_CALLOFF'
        ELSE 'UNKNOWN' END
      ELSE 'UNKNOWN'
    END
    """

    con.execute(f"""
      CREATE TABLE tn AS
      SELECT {source} source, {tid} tender_id, {country} country,
             {buyer_key} buyer_key, {buyer_name} buyer_name, {currency} currency,
             {est} estimated_value, {pub} publication_date, {title} title,
             {scope} scope_text, {cpv} cpv_code, {proc} procedure_text,
             {url} official_url, {micro} micro_niche, {route} route_band
      FROM read_parquet(?)
      WHERE ({micro}) IS NOT NULL
    """, [a.historical])

    con.execute(f"""
      CREATE TEMP TABLE aw AS
      SELECT {asrc} source, {atid} tender_id, {award_id} award_id,
             {award_value} award_value, {award_currency} award_currency,
             {bidders} bidder_count
      FROM read_parquet(?)
    """, [a.awards])

    con.execute(f"""
      CREATE TEMP TABLE br AS
      SELECT {bsrc} source, {baid} award_id, {supplier_id} supplier_id,
             {supplier_name} supplier_name
      FROM read_parquet(?)
    """, [a.bridge])

    # Tender-level bidder statistics avoid inflating recurrence when a tender has
    # multiple awards. Award-value quantiles are still computed from award rows.
    con.execute("""
      CREATE TEMP TABLE aw_tender AS
      SELECT source,tender_id,
             median(bidder_count) FILTER (WHERE bidder_count IS NOT NULL AND bidder_count>=0) median_bidders,
             count(*) FILTER (WHERE bidder_count IS NOT NULL AND bidder_count>=0) bidder_rows,
             count(*) FILTER (WHERE bidder_count=1) one_bid_rows,
             count(*) award_rows
      FROM aw GROUP BY 1,2
    """)

    con.execute("""
      CREATE TEMP TABLE repeat_buyers AS
      SELECT micro_niche,source,country,route_band,currency,buyer_key,
             max(buyer_name) buyer_name,count(*) procurements,
             min(publication_date) first_date,max(publication_date) last_date,
             median(estimated_value) FILTER (WHERE estimated_value>0) median_estimated_value
      FROM tn
      WHERE buyer_key<>''
      GROUP BY 1,2,3,4,5,6
      HAVING count(*)>=2
    """)

    # Supplier fractional weights: a consortium award contributes total weight 1,
    # split evenly across its supplier links. This prevents consortium duplication.
    con.execute("""
      CREATE TEMP TABLE br_count AS
      SELECT source,award_id,count(*) n_suppliers
      FROM br WHERE supplier_id<>'' GROUP BY 1,2
    """)
    con.execute("""
      CREATE TEMP TABLE supplier_weights AS
      SELECT t.micro_niche,t.source,t.country,t.route_band,t.currency,
             b.supplier_id,max(b.supplier_name) supplier_name,
             sum(1.0/nullif(c.n_suppliers,0)) fractional_awards
      FROM tn t
      JOIN aw a USING(source,tender_id)
      JOIN br b USING(source,award_id)
      JOIN br_count c USING(source,award_id)
      WHERE b.supplier_id<>''
      GROUP BY 1,2,3,4,5,6
    """)
    con.execute("""
      CREATE TEMP TABLE supplier_structure AS
      WITH x AS (
        SELECT *, sum(fractional_awards) OVER (PARTITION BY micro_niche,source,country,route_band,currency) total_w
        FROM supplier_weights
      )
      SELECT micro_niche,source,country,route_band,currency,
             count(*) supplier_count,
             max(fractional_awards/nullif(total_w,0)) top_supplier_share,
             sum(power(100.0*fractional_awards/nullif(total_w,0),2)) hhi
      FROM x GROUP BY 1,2,3,4,5
    """)

    con.execute("""
      CREATE TEMP TABLE cohort_raw AS
      WITH base AS (
        SELECT t.micro_niche,t.source,t.country,t.route_band,t.currency,
               count(*) records,count(DISTINCT NULLIF(t.buyer_key,'')) buyers,
               median(t.estimated_value) FILTER (WHERE t.estimated_value>0) median_estimated_value,
               median(at.median_bidders) FILTER (WHERE at.bidder_rows>0) median_bidders,
               sum(coalesce(at.bidder_rows,0)) bidder_rows,
               sum(coalesce(at.one_bid_rows,0)) one_bid_rows
        FROM tn t LEFT JOIN aw_tender at USING(source,tender_id)
        GROUP BY 1,2,3,4,5
      ), av AS (
        SELECT t.micro_niche,t.source,t.country,t.route_band,t.currency,
               count(*) FILTER (WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) compatible_award_rows,
               quantile_cont(a.award_value,0.25) FILTER (WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) p25_award_value,
               median(a.award_value) FILTER (WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) median_award_value,
               quantile_cont(a.award_value,0.75) FILTER (WHERE a.award_value>0 AND t.currency<>'UNKNOWN' AND a.award_currency=t.currency) p75_award_value
        FROM tn t LEFT JOIN aw a USING(source,tender_id)
        GROUP BY 1,2,3,4,5
      ), rb AS (
        SELECT micro_niche,source,country,route_band,currency,count(*) repeat_buyers,sum(procurements) repeat_procurements
        FROM repeat_buyers GROUP BY 1,2,3,4,5
      )
      SELECT b.*,a.compatible_award_rows,a.p25_award_value,a.median_award_value,a.p75_award_value,
             coalesce(r.repeat_buyers,0) repeat_buyers,coalesce(r.repeat_procurements,0) repeat_procurements,
             CASE WHEN b.buyers>0 THEN 1.0*coalesce(r.repeat_buyers,0)/b.buyers ELSE 0 END repeat_buyer_rate,
             CASE WHEN b.bidder_rows>0 THEN 1.0*b.one_bid_rows/b.bidder_rows ELSE NULL END single_bid_rate,
             s.supplier_count,s.top_supplier_share,s.hhi
      FROM base b JOIN av a USING(micro_niche,source,country,route_band,currency)
      LEFT JOIN rb r USING(micro_niche,source,country,route_band,currency)
      LEFT JOIN supplier_structure s USING(micro_niche,source,country,route_band,currency)
    """)

    lean_prior = """
      CASE micro_niche
        WHEN 'Web accessibility / WCAG audit-remediation' THEN 1.00
        WHEN 'WordPress / Drupal / CMS implementation' THEN 0.95
        WHEN 'Website maintenance / hosting / support' THEN 0.95
        WHEN 'Website design / redesign / development' THEN 0.90
        WHEN 'Annual report / publication layout-production' THEN 0.95
        WHEN 'Graphic design / DTP / visual identity' THEN 1.00
        WHEN 'Video production / editing / motion' THEN 0.85
        WHEN 'Subtitling / captioning' THEN 1.00
        WHEN 'Transcription / speech-to-text' THEN 1.00
        WHEN 'Translation services' THEN 0.90
        WHEN 'Document scanning / digitization / OCR' THEN 0.85
        WHEN 'Data entry / document indexing' THEN 0.80
        WHEN 'Social media / community management' THEN 0.90
        WHEN 'SEO / digital marketing' THEN 0.90
        WHEN 'Media / press monitoring' THEN 0.85
        WHEN 'Market research / surveys / polling' THEN 0.70
        WHEN 'Mailing / fulfilment / routing' THEN 0.70
        WHEN 'Commercial printing / print production' THEN 0.75
        WHEN 'Promotional merchandise / branded goods' THEN 0.65
        WHEN 'Software licence renewal / licensing' THEN 0.65
        WHEN 'SaaS / cloud software subscription' THEN 0.65
        WHEN 'Document-management software licensing' THEN 0.65
        WHEN 'LMS / e-learning platform software' THEN 0.65
        ELSE 0.50 END
    """
    route_factor = """
      CASE route_band
        WHEN 'OPEN_PUBLIC' THEN 1.0
        WHEN 'COMPETITIVE_OTHER' THEN 0.8
        WHEN 'LIMITED_INVITATION' THEN 0.55
        WHEN 'UNKNOWN' THEN 0.45
        WHEN 'FRAMEWORK_DPS_CALLOFF' THEN 0.30
        WHEN 'DIRECT_NONCOMPETITIVE' THEN 0.20
        ELSE 0.40 END
    """

    con.execute(f"""
      CREATE TABLE ranked AS
      WITH p AS (
        SELECT *,
          percent_rank() OVER (ORDER BY records) vol_pct,
          percent_rank() OVER (ORDER BY buyers) buyer_pct,
          greatest(0.0,least(1.0,repeat_buyer_rate*3.0)) repeat_component,
          CASE WHEN bidder_rows>=10 AND median_bidders IS NOT NULL
               THEN greatest(0.0,least(1.0,(8.0-median_bidders)/7.0)) ELSE 0.5 END competition_component,
          CASE WHEN supplier_count>=5 AND top_supplier_share IS NOT NULL
               THEN greatest(0.0,least(1.0,1.0-top_supplier_share)) ELSE 0.5 END fragmentation_component,
          CASE WHEN median_award_value IS NULL THEN 0.5
               WHEN median_award_value<20000 THEN 0.55
               WHEN median_award_value<=500000 THEN 1.0
               WHEN median_award_value<=1500000 THEN 0.8
               WHEN median_award_value<=5000000 THEN 0.45
               ELSE 0.20 END value_fit_component,
          {lean_prior} lean_component,
          {route_factor} route_component
        FROM cohort_raw WHERE records>=3
      )
      SELECT *, round(100.0*(
          0.18*vol_pct + 0.12*buyer_pct + 0.12*repeat_component +
          0.12*competition_component + 0.08*fragmentation_component +
          0.10*value_fit_component + 0.18*lean_component + 0.10*route_component
        ),2) historical_spm_score,
        CASE WHEN route_band IN ('OPEN_PUBLIC','COMPETITIVE_OTHER') THEN 'OPEN_BID'
             WHEN route_band='DIRECT_NONCOMPETITIVE' THEN 'DIRECT_BUYER'
             ELSE 'OTHER_ROUTE' END market_motion
      FROM p
    """)

    rank_headers = [
        "micro_niche","source","country","route","currency","records","buyers","repeat_buyers","repeat_buyer_rate",
        "median_estimated_value","compatible_award_rows","p25_award_value","median_award_value","p75_award_value",
        "bidder_rows","median_bidders","single_bid_pct","supplier_count","top_supplier_share_pct","hhi",
        "historical_spm_score","market_motion",
    ]
    rank_rows = con.execute("""
      SELECT micro_niche,source,country,route_band,currency,records,buyers,repeat_buyers,round(100*repeat_buyer_rate,2),
             median_estimated_value,compatible_award_rows,p25_award_value,median_award_value,p75_award_value,
             bidder_rows,median_bidders,round(100*single_bid_rate,2),supplier_count,round(100*top_supplier_share,2),round(hhi,2),
             historical_spm_score,market_motion
      FROM ranked ORDER BY historical_spm_score DESC,records DESC
    """).fetchall()
    write_csv(out / "micro_niche_rank.csv", rank_headers, rank_rows)

    open_rows = con.execute("""
      SELECT micro_niche,source,country,route_band,currency,records,buyers,repeat_buyers,round(100*repeat_buyer_rate,2),
             median_estimated_value,p25_award_value,median_award_value,p75_award_value,bidder_rows,median_bidders,
             round(100*single_bid_rate,2),supplier_count,round(100*top_supplier_share,2),round(hhi,2),historical_spm_score
      FROM ranked WHERE market_motion='OPEN_BID'
      ORDER BY historical_spm_score DESC,records DESC
    """).fetchall()
    write_csv(out / "open_bid_micro_niche_rank.csv", rank_headers[:-1], open_rows)

    direct_rows = con.execute("""
      SELECT micro_niche,source,country,route_band,currency,records,buyers,repeat_buyers,round(100*repeat_buyer_rate,2),
             median_estimated_value,p25_award_value,median_award_value,p75_award_value,bidder_rows,median_bidders,
             round(100*single_bid_rate,2),supplier_count,round(100*top_supplier_share,2),round(hhi,2),historical_spm_score
      FROM ranked WHERE market_motion='DIRECT_BUYER'
      ORDER BY historical_spm_score DESC,records DESC
    """).fetchall()
    write_csv(out / "direct_buyer_micro_niche_rank.csv", rank_headers[:-1], direct_rows)

    repeat_headers = ["micro_niche","source","country","route","currency","buyer","procurements","first_date","last_date","median_estimated_value"]
    repeat_rows = con.execute("""
      SELECT micro_niche,source,country,route_band,currency,buyer_name,procurements,first_date,last_date,median_estimated_value
      FROM repeat_buyers ORDER BY procurements DESC,micro_niche,source
      LIMIT 10000
    """).fetchall()
    write_csv(out / "repeat_buyers_micro_niche.csv", repeat_headers, repeat_rows)

    supplier_headers = ["micro_niche","source","country","route","currency","supplier","fractional_awards","share_pct"]
    supplier_rows = con.execute("""
      WITH x AS (
        SELECT *,sum(fractional_awards) OVER (PARTITION BY micro_niche,source,country,route_band,currency) tw,
               row_number() OVER (PARTITION BY micro_niche,source,country,route_band,currency ORDER BY fractional_awards DESC,supplier_id) rn
        FROM supplier_weights
      )
      SELECT micro_niche,source,country,route_band,currency,supplier_name,round(fractional_awards,3),round(100*fractional_awards/nullif(tw,0),2)
      FROM x WHERE rn<=10 ORDER BY micro_niche,source,country,route_band,currency,rn
    """).fetchall()
    write_csv(out / "top_winners_micro_niche.csv", supplier_headers, supplier_rows)

    example_headers = ["micro_niche","source","country","route","currency","buyer","title","estimated_value","publication_date","url"]
    example_rows = con.execute("""
      WITH z AS (
        SELECT *,row_number() OVER (PARTITION BY micro_niche,source,country,route_band ORDER BY hash(tender_id,title)) rn
        FROM tn
      )
      SELECT micro_niche,source,country,route_band,currency,buyer_name,title,estimated_value,publication_date,official_url
      FROM z WHERE rn<=6 ORDER BY micro_niche,source,country,route_band,rn
    """).fetchall()
    write_csv(out / "representative_examples.csv", example_headers, example_rows)

    counts = con.execute("""
      SELECT count(*) records,count(DISTINCT tender_id) distinct_tenders,count(DISTINCT micro_niche) micro_niches,
             count(DISTINCT buyer_key) FILTER (WHERE buyer_key<>'') buyers
      FROM tn
    """).fetchone()
    top_open = con.execute("""
      SELECT micro_niche,source,country,currency,records,buyers,median_award_value,median_bidders,historical_spm_score
      FROM ranked WHERE market_motion='OPEN_BID' ORDER BY historical_spm_score DESC,records DESC LIMIT 25
    """).fetchall()

    manifest = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_grain": "GLOBAL_CORE_V4_NOTICE_FIRST",
        "counts": {"classified_records": counts[0], "distinct_tenders": counts[1], "micro_niches": counts[2], "buyers": counts[3]},
        "safety": {
            "historical_only": True,
            "satisfies_dce_gates": False,
            "affects_final_verdict": False,
            "no_fx_mixing": True,
            "consortium_award_fractionalized": True,
            "unknown_is_not_zero": True,
        },
        "scoring": {
            "label": "historical_spm_score",
            "meaning": "retrieval/market prior only; not bid eligibility",
            "components": ["volume","buyer breadth","repeat buyers","competition where covered","supplier fragmentation","value fit","lean feasibility prior","route quality"],
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")

    lines = [
        "# SPM Micro-Niche Intelligence v1", "",
        f"Version: `{VERSION}`", "",
        f"Classified notice-first records: **{counts[0]:,}** across **{counts[2]}** high-precision micro-niches.", "",
        "Historical only: this is a market/retrieval prior. DCE still controls all eligibility and delivery gates.", "",
        "## Top open-bid cohorts", "",
        "|Micro-niche|Source|Country|Currency|Records|Buyers|Median award|Median bidders|SPM hist. score|",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in top_open:
        lines.append("|" + "|".join("" if x is None else str(x) for x in r) + "|")
    lines += ["", "## Outputs", "", "- `micro_niche_rank.csv` — all route-aware cohorts", "- `open_bid_micro_niche_rank.csv` — public/competitive bidding motion", "- `direct_buyer_micro_niche_rank.csv` — direct-buyer demand evidence only", "- `repeat_buyers_micro_niche.csv` — buyer×micro-niche recurrence", "- `top_winners_micro_niche.csv` — winner structure with consortium fractionalisation", "- `representative_examples.csv` — deterministic historical examples", "- `manifest.json` — provenance/safety/scoring contract"]
    (out / "REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

    print(json.dumps(manifest,indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
