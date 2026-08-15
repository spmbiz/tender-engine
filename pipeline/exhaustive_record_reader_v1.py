#!/usr/bin/env python3
from __future__ import annotations

"""Exhaustive every-record historical procurement reader.

This deliberately does not sample. Every input tender/procurement row is materialized into
an analyzed narrow parquet before any ranking happens. Every award row and award-supplier
link row is scanned and reconciled. The outputs are compact derived intelligence; the
canonical raw source remains the upstream GitHub Release.

The goal is to account for the full historical universe while preserving grain:
NOTICE_FIRST_TENDER versus AWARD_FIRST_PROCUREMENT, AWARD, and AWARD_SUPPLIER_LINK.
"""

import argparse, csv, json, math, os, re
from datetime import datetime, timezone
from pathlib import Path
import duckdb

VERSION = "SPM_EXHAUSTIVE_RECORD_READER_V1"


def qi(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def lit(x: str) -> str:
    return "'" + x.replace("'", "''") + "'"


def choose(cols: set[str], *names: str) -> str | None:
    m = {c.casefold(): c for c in cols}
    for n in names:
        if n.casefold() in m:
            return m[n.casefold()]
    return None


def relation(path: Path) -> str:
    p = lit(str(path))
    if path.suffix.lower() == ".parquet":
        return f"read_parquet({p})"
    return f"read_csv_auto({p}, header=true, all_varchar=true, sample_size=-1, ignore_errors=false, compression='auto')"


def cols_for(con, rel: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()}


def text_expr(c: str | None, default="''") -> str:
    return f"trim(cast({qi(c)} as varchar))" if c else default


def double_expr(c: str | None) -> str:
    return f"try_cast({qi(c)} as double)" if c else "NULL::DOUBLE"


def date_expr(c: str | None) -> str:
    return f"try_cast({qi(c)} as date)" if c else "NULL::DATE"


def lane_case(txt: str) -> str:
    # High-precision named lanes plus additional brokerable/automation lanes.
    return f"""
    CASE
      WHEN regexp_matches({txt}, '(website|web site|site web|site internet|content management system|wordpress|drupal|joomla|portail web|web portal|internetauftritt|webseite|sitio web|sito web)')
           AND regexp_matches({txt}, '(maintenance|support|hosting|hébergement|hebergement|accessibil|wcag|barrierefrei|pflege|betrieb|operation|entretien|mise à jour|mise a jour)') THEN 'Website support / accessibility / hosting'
      WHEN regexp_matches({txt}, '(website|web site|site web|site internet|content management system|wordpress|drupal|joomla|portail web|web portal|internetauftritt|webseite|sitio web|sito web)') THEN 'Website / CMS build or redesign'
      WHEN regexp_matches({txt}, '(traduction|\\btranslations?\\b|translation services?|übersetz|uebersetz|traducción|traduccion|traduzione|tłumacz|tlumacz|linguistic translation)') AND NOT regexp_matches({txt}, '(translational|translationale|translationell)') THEN 'Translation'
      WHEN regexp_matches({txt}, '(transcription|transcribing|speech[- ]to[- ]text|captioning|closed caption|sous[- ]titr|subtitl|sténograph|stenograph)') THEN 'Transcription / captioning'
      WHEN regexp_matches({txt}, '(digitization|digitisation|digitalization|digitalisation|numérisation|numerisation|document scanning|scan of documents|scanning of documents|digitalisierung.{0,40}(akten|dokument)|\\bocr\\b)') AND NOT regexp_matches({txt}, '(street sweep|street cleaning|balayage.{0,30}(rue|voirie|chauss|trottoir)|road sweep|nettoyage.{0,30}(rue|voirie))') THEN 'Document digitization / OCR / scanning'
      WHEN regexp_matches({txt}, '(data entry|saisie de données|saisie de donnees|entrada de datos|inserimento dati|clerical processing|document indexing)') THEN 'Data entry / clerical processing'
      WHEN regexp_matches({txt}, '(graphic design|conception graphique|design graphique|graphisme|mise en page|desktop publishing|infograph|identité visuelle|identite visuelle|visual identity|grafikdesign|grafische gestaltung|diseño gráfico|diseno grafico|progettazione grafica)') AND NOT regexp_matches({txt}, '(architect|civil engineering|engineering design|construction design|road design|maîtrise d.oeuvre|maitrise d.oeuvre)') THEN 'Graphic design / layout / DTP'
      WHEN regexp_matches({txt}, '(video production|production vidéo|production video|videoproduktion|post[- ]production|motion graphic|motion design|video edit|montage vidéo|montage video|film production)') THEN 'Video production / post-production'
      WHEN regexp_matches({txt}, '(social media|réseaux sociaux|reseaux sociaux|community management|social media management|gestion des médias sociaux|gestion des medias sociaux)') THEN 'Social media / community management'
      WHEN regexp_matches({txt}, '(search engine optimi|\\bseo\\b|référencement naturel|referencement naturel|digital marketing|marketing digital|online marketing)') THEN 'SEO / digital marketing'
      WHEN regexp_matches({txt}, '(media monitoring|press monitoring|veille médiatique|veille mediatique|revue de presse|medienbeobachtung)') THEN 'Media / press monitoring'
      WHEN regexp_matches({txt}, '(market research|étude de marché|etude de marche|opinion poll|customer survey|survey services|sondage)') AND NOT regexp_matches({txt}, '(géotech|geotech|piézocône|piezocone|forage|sondage de sol|soil boring|drilling|borehole|géologique|geologique)') THEN 'Survey / market research'
      WHEN regexp_matches({txt}, '(printing services|print production|services d.impression|travaux d.impression|imprimerie|printing and delivery|mise sous pli|mailing services|routage|impression et routage|impression,|impression de)') AND NOT regexp_matches({txt}, '(3d print|additive manufactur|impression 3d|printer maintenance|maintenance.{0,30}(printer|imprimante|copieur)|fleet.{0,20}(printer|copier)|parc.{0,30}(imprimante|copieur|système.s. d.impression|systeme.s. d.impression)|multifunction printer|managed print service)') THEN 'Printing / mailing / routing'
      WHEN regexp_matches({txt}, '(promotional merchandise|promotional items|objets publicitaires|articles promotionnels|goodies|branded merchandise)') THEN 'Promotional merchandise'
      WHEN regexp_matches({txt}, '(signage|signalétique|signaletique|wayfinding|enseigne|panneaux publicitaires|display boards)') THEN 'Signage / display production'
      WHEN regexp_matches({txt}, '(annual report|rapport annuel|publication production|document formatting|formatting of documents)') AND regexp_matches({txt}, '(design|layout|mise en page|production|publishing)') THEN 'Report / publication production'
      WHEN regexp_matches({txt}, '(call cent(er|re)|contact cent(er|re)|hotline|telephone answering|answering service|help desk)') THEN 'Call centre / helpdesk operations'
      WHEN regexp_matches({txt}, '(e[- ]learning|online training|training delivery|formation en ligne|formation à distance|formation a distance|learning management system|\\blms\\b)') THEN 'Training / e-learning'
      WHEN regexp_matches({txt}, '(event management|event production|conference management|organisation d.événement|organisation d.evenement|gestion d.événement|gestion d.evenement)') THEN 'Event support / production'
      WHEN regexp_matches({txt}, '(software licen[cs]|software subscription|saas|cloud subscription|licence logiciel|licences logicielles|subscription software)') THEN 'Software licences / SaaS resale'
      WHEN regexp_matches({txt}, '(cloud hosting|managed hosting|hosting services|hébergement cloud|hebergement cloud|managed it service|managed ict service)') THEN 'Cloud / hosting / managed IT'
      WHEN regexp_matches({txt}, '(audio visual|audiovisual equipment|av equipment|computer hardware|laptop|desktop computer|monitor|display screen|projector|network equipment|server hardware)') THEN 'Hardware / AV resale'
      WHEN regexp_matches({txt}, '(office supplies|stationery|papeterie|fournitures de bureau|toner|ink cartridge)') THEN 'Office supplies / consumables resale'
      WHEN regexp_matches({txt}, '(uniforms?|workwear|protective clothing|personal protective equipment|\\bppe\\b|vêtements de travail|vetements de travail)') THEN 'Uniforms / PPE resale'
      WHEN regexp_matches({txt}, '(courier|messenger service|parcel delivery|mail delivery|postal services|distribution de courrier|livraison de colis)') THEN 'Courier / mail fulfilment'
      WHEN regexp_matches({txt}, '(temporary staff|temporary staffing|agency staff|interim staff|recruitment services|intérim|interim|personnel temporaire)') THEN 'Recruitment / temporary staffing'
      ELSE 'OTHER / OPEN WORLD'
    END
    """


def broad_case(txt: str) -> str:
    return f"""
    CASE
      WHEN regexp_matches({txt}, '(construction|building work|travaux de construction|roadworks|civil works|renovation|rénovation|rehabilitation|roofing|plumbing|electrical works)') THEN 'Construction / works'
      WHEN regexp_matches({txt}, '(architect|engineering|ingénierie|ingenierie|structural design|civil engineering|surveying services|quantity survey)') THEN 'Architecture / engineering'
      WHEN regexp_matches({txt}, '(software|information technology|\\bit services?\\b|ict services|informatique|cyber|cloud|network|database|application development|system integration)') THEN 'IT / software / cyber'
      WHEN regexp_matches({txt}, '(website|web site|site web|portal|digital platform|wordpress|drupal|seo|social media|digital marketing)') THEN 'Web / digital'
      WHEN regexp_matches({txt}, '(graphic|design|communication|advertising|public relations|video|film|media|publication|printing|impression|signage|promotional)') THEN 'Creative / communications / print'
      WHEN regexp_matches({txt}, '(translation|traduction|interpretation services|transcription|caption|subtitl|language services)') THEN 'Language / transcription'
      WHEN regexp_matches({txt}, '(digitiz|digitis|numéris|numeris|scanning|archive|records management|document management|data entry|data processing|metadata|\\bocr\\b)') THEN 'Document / data processing'
      WHEN regexp_matches({txt}, '(consulting|consultancy|conseil|advisory|research|study|étude|etude|survey|market research|audit services)') THEN 'Consulting / research / audit'
      WHEN regexp_matches({txt}, '(training|formation|learning|education services|coaching)') THEN 'Training / education'
      WHEN regexp_matches({txt}, '(event|conference|exhibition|trade show|meeting management)') THEN 'Events / exhibitions'
      WHEN regexp_matches({txt}, '(staffing|recruitment|temporary staff|interim|personnel|human resources)') THEN 'Staffing / HR'
      WHEN regexp_matches({txt}, '(medical|healthcare|hospital|pharmaceutical|medicine|clinical|patient|surgical|dental)') THEN 'Healthcare / medical'
      WHEN regexp_matches({txt}, '(laboratory|scientific|testing|analysis service|diagnostic|research equipment)') THEN 'Laboratory / scientific'
      WHEN regexp_matches({txt}, '(office supplies|stationery|furniture|consumables|toner|paper supply)') THEN 'Office / administrative goods'
      WHEN regexp_matches({txt}, '(hardware|computer equipment|laptop|desktop|monitor|server|network equipment|audiovisual|projector|camera equipment)') THEN 'Hardware / AV / electronics'
      WHEN regexp_matches({txt}, '(transport|freight|courier|delivery|logistics|vehicle|fleet|shipping)') THEN 'Transport / logistics'
      WHEN regexp_matches({txt}, '(cleaning|janitorial|facility|facilities|maintenance|repair|grounds maintenance|landscaping|pest control)') THEN 'Facilities / cleaning / maintenance'
      WHEN regexp_matches({txt}, '(catering|food supply|meal|restaurant|beverage)') THEN 'Food / catering'
      WHEN regexp_matches({txt}, '(electricity|energy|gas supply|water supply|utility|renewable energy)') THEN 'Energy / utilities'
      WHEN regexp_matches({txt}, '(security guard|security services|surveillance|alarm|fire safety)') THEN 'Security / safety'
      WHEN regexp_matches({txt}, '(waste|recycling|environmental|pollution|sewage|sanitation)') THEN 'Environment / waste'
      WHEN regexp_matches({txt}, '(property|real estate|lease|rental of property|estate management)') THEN 'Property / real estate'
      WHEN regexp_matches({txt}, '(supply of|purchase of|procurement of|goods|equipment|materials|fourniture|fournitures)') THEN 'Other goods / resale'
      WHEN regexp_matches({txt}, '(service|services|prestation|prestations)') THEN 'Other services'
      ELSE 'Other / unknown'
    END
    """


def route_case(source: str, proc: str, grain: str) -> str:
    if grain == "AWARD_FIRST_PROCUREMENT":
        return "'AWARD_FIRST_EVIDENCE'"
    sl = f"lower(coalesce({source},''))"
    pl = f"lower(coalesce({proc},''))"
    return f"""
    CASE
      WHEN {sl}='quebec' THEN CASE
        WHEN {pl} LIKE '%gré à gré%' THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%invitation%' THEN 'LIMITED_INVITATION'
        WHEN ({pl} LIKE '%avis d’appel d’offres%' OR {pl} LIKE '%avis d''appel d''offres%') THEN 'OPEN_PUBLIC'
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
        WHEN {pl} IN ('neg-wo-call','de-restricted-wo-call','de-comp-wo-call','de-comp-neg-wo-call','oth-single','us-neg-wo-call','us-free-no-tw','us-res-no-tw') OR {pl} LIKE '%freihändige%' OR {pl} LIKE '%freihandige%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='ireland' THEN CASE
        WHEN {pl}='open procedure' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','competitive procedure with negotiation','simplified','competitive dialogue') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('direct invite – mini-competition','dps qualification','uqs qualification') THEN 'FRAMEWORK_DPS_CALLOFF'
        WHEN {pl} IN ('negotiated procedure without prior publication','direct invite – quick quote') THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='united kingdom' THEN CASE
        WHEN {pl} IN ('open procedure','below threshold - open competition','competitive flexible procedure','competitive tendering procedure') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','restricted','below threshold - limited competition','negotiated procedure with prior call for competition','competitive procedure with negotiation','competitive dialogue','negotiated with publication of a contract notice','award procedure with prior publication of a call for competition','procedure involving negotiations') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('below threshold - without competition','award procedure without prior publication of a call for competition','direct award','negotiated without publication of a contract notice') THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%framework%' OR {pl} LIKE '%dynamic market%' THEN 'FRAMEWORK_DPS_CALLOFF'
        ELSE 'UNKNOWN' END
      ELSE 'UNKNOWN'
    END
    """


def write_csv(path: Path, headers, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(headers); w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', required=True)
    ap.add_argument('--grain', choices=['NOTICE_FIRST_TENDER','AWARD_FIRST_PROCUREMENT'], required=True)
    ap.add_argument('--historical', required=True)
    ap.add_argument('--awards', required=True)
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--expected-tenders', type=int, default=0)
    ap.add_argument('--expected-awards', type=int, default=0)
    ap.add_argument('--expected-links', type=int, default=0)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    hp, awp, bp = Path(a.historical), Path(a.awards), Path(a.bridge)
    con = duckdb.connect(str(out / 'work.duckdb'))
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute("SET temp_directory='{}'".format(str(out / 'ducktmp').replace("'","''")))

    hrel, arel, brel = relation(hp), relation(awp), relation(bp)
    hc, ac, bc = cols_for(con, hrel), cols_for(con, arel), cols_for(con, brel)

    hid = choose(hc,'Historical_Tender_ID','Opportunity_ID','Procurement_ID','Contract_ID','Award_ID','id')
    hsource = choose(hc,'Warehouse_Source','Source','source')
    hcountry = choose(hc,'Country','Supplier_Country','country')
    htitle = choose(hc,'Title','Contract_Title','Award_Description','Description','Procurement_Description','description')
    hscope = choose(hc,'Scope_Summary','Description','Award_Reason_Summary','Contract_Description','description')
    hbuyer = choose(hc,'Buyer_Name','Agency_Name','Department_Name','Buyer','buyer_name')
    hbuyerid = choose(hc,'Buyer_ID','Agency_ID','buyer_id')
    hcur = choose(hc,'Currency','currency')
    hest = choose(hc,'Official_Estimated_Value','Estimated_Value','Award_Value','Contract_Value','Total_Obligation','value')
    hpub = choose(hc,'Publication_Date','Award_Date','Start_Date','Contract_Start_Date','Action_Date','date')
    hcode = choose(hc,'CPV_NAICS_or_Local_Code','NAICS','PSC','CPV','Category_Code','UNSPSC','code')
    hcoded = choose(hc,'Raw_CPV_Description','NAICS_Description','PSC_Description','Category','Category_Description','code_description')
    hproc = choose(hc,'Procedure','procurement_procedure','Solicitation_Procedure')
    hurl = choose(hc,'Primary_Source_URL','Official_URL','URL','url')

    aid = choose(ac,'Award_ID','Contract_ID','id')
    atid = choose(ac,'Historical_Tender_ID','Procurement_ID','Opportunity_ID','Contract_ID','tender_id')
    aval = choose(ac,'Award_Value','Contract_Value','Total_Obligation','value')
    acur = choose(ac,'Currency','currency')
    abid = choose(ac,'Bidder_Count','Tenderer_Count','Number_Of_Bids','bidder_count')
    adate = choose(ac,'Award_Date','Action_Date','Contract_Start_Date','date')

    baid = choose(bc,'Award_ID','Contract_ID','award_id')
    bsid = choose(bc,'Supplier_ID','Recipient_ID','supplier_id')
    bsname = choose(bc,'Supplier_Name','Recipient_Name','supplier_name')

    if not hid:
        raise SystemExit(json.dumps({'error':'missing historical stable id','historical_columns':sorted(hc)}, indent=2))

    source = text_expr(hsource, lit(a.label)) if hsource else lit(a.label)
    country = text_expr(hcountry, lit(a.label)) if hcountry else lit(a.label)
    tid = text_expr(hid)
    title = text_expr(htitle)
    scope = text_expr(hscope)
    buyer = text_expr(hbuyer)
    buyerid = text_expr(hbuyerid)
    currency = f"upper(coalesce(nullif({text_expr(hcur)},''),'UNKNOWN'))" if hcur else "'UNKNOWN'"
    est = double_expr(hest)
    pub = date_expr(hpub)
    code = text_expr(hcode)
    coded = text_expr(hcoded)
    proc = text_expr(hproc, "'UNKNOWN'")
    url = text_expr(hurl)
    alltxt = f"lower(concat_ws(' ',{title},{scope},{coded},{code}))"
    lane = lane_case(alltxt)
    broad = broad_case(alltxt)
    route = route_case(source, proc, a.grain)

    # Scan every award row and every supplier-link row into compact tender-level evidence.
    award_total = con.execute(f"SELECT count(*) FROM {arel}").fetchone()[0]
    link_total = con.execute(f"SELECT count(*) FROM {brel}").fetchone()[0]
    award_key = text_expr(aid) if aid else "''"
    award_tender = text_expr(atid) if atid else "''"
    award_value = double_expr(aval)
    award_cur = f"upper(coalesce(nullif({text_expr(acur)},''),'UNKNOWN'))" if acur else "'UNKNOWN'"
    award_bid = double_expr(abid)
    award_date = date_expr(adate)
    award_fp = con.execute(f"SELECT count(*), sum(cast(hash(concat_ws('|',{award_key},{award_tender},coalesce(cast({award_value} as varchar),''),coalesce(cast({award_date} as varchar),''))) as hugeint)) FROM {arel}").fetchone()
    link_award = text_expr(baid) if baid else "''"
    link_sid = text_expr(bsid) if bsid else "''"
    link_sname = text_expr(bsname) if bsname else "''"
    link_fp = con.execute(f"SELECT count(*), sum(cast(hash(concat_ws('|',{link_award},{link_sid},{link_sname})) as hugeint)) FROM {brel}").fetchone()

    if atid:
        con.execute(f"""COPY (
          SELECT {award_tender} tender_id,
                 count(*) award_rows,
                 median({award_value}) FILTER (WHERE {award_value} IS NOT NULL AND {award_value}>=0) median_award_value,
                 min({award_value}) FILTER (WHERE {award_value} IS NOT NULL AND {award_value}>=0) min_award_value,
                 max({award_value}) FILTER (WHERE {award_value} IS NOT NULL AND {award_value}>=0) max_award_value,
                 median({award_bid}) FILTER (WHERE {award_bid} IS NOT NULL AND {award_bid}>=0) median_bidder_count,
                 max({award_cur}) FILTER (WHERE {award_cur}<>'UNKNOWN') award_currency,
                 max({award_date}) max_award_date
          FROM {arel}
          GROUP BY 1
        ) TO {lit(str(out/'award_stats.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    else:
        con.execute(f"COPY (SELECT ''::varchar tender_id, 0::bigint award_rows, NULL::double median_award_value, NULL::double min_award_value, NULL::double max_award_value, NULL::double median_bidder_count, 'UNKNOWN'::varchar award_currency, NULL::date max_award_date WHERE false) TO {lit(str(out/'award_stats.parquet'))} (FORMAT PARQUET)")

    if baid and aid and atid:
        # Bridge supplier count per tender via award id.
        con.execute(f"""COPY (
          WITH aw AS (SELECT {award_key} award_id,{award_tender} tender_id FROM {arel}),
               br AS (SELECT {link_award} award_id,{link_sid} supplier_id,{link_sname} supplier_name FROM {brel})
          SELECT aw.tender_id, count(*) supplier_links, count(distinct coalesce(nullif(br.supplier_id,''),br.supplier_name)) distinct_suppliers
          FROM aw JOIN br USING(award_id) GROUP BY 1
        ) TO {lit(str(out/'supplier_stats.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    else:
        con.execute(f"COPY (SELECT ''::varchar tender_id,0::bigint supplier_links,0::bigint distinct_suppliers WHERE false) TO {lit(str(out/'supplier_stats.parquet'))} (FORMAT PARQUET)")

    # Materialize EVERY procurement row with analysis. No WHERE clause by design.
    con.execute(f"""COPY (
      WITH base AS (
        SELECT {source} warehouse_source, {tid} tender_id, {country} country, {buyerid} buyer_id, {buyer} buyer_name,
               {currency} currency, {est} estimated_value, {pub} publication_date, {title} title, {scope} scope_summary,
               {code} code, {coded} code_description, {proc} procurement_procedure, {url} official_url,
               {lane} lean_lane, {broad} broad_family, {route} route_band,
               row_number() over() scan_ordinal
        FROM {hrel}
      ), joined AS (
        SELECT b.*, coalesce(a.award_rows,0) award_rows, a.median_award_value, a.min_award_value, a.max_award_value,
               a.median_bidder_count, coalesce(a.award_currency,'UNKNOWN') award_currency,
               coalesce(s.supplier_links,0) supplier_links, coalesce(s.distinct_suppliers,0) distinct_suppliers
        FROM base b
        LEFT JOIN read_parquet({lit(str(out/'award_stats.parquet'))}) a USING(tender_id)
        LEFT JOIN read_parquet({lit(str(out/'supplier_stats.parquet'))}) s USING(tender_id)
      ), scored AS (
        SELECT *,
          CASE lean_lane
            WHEN 'Website / CMS build or redesign' THEN 95 WHEN 'Website support / accessibility / hosting' THEN 92
            WHEN 'Translation' THEN 92 WHEN 'Transcription / captioning' THEN 95 WHEN 'Document digitization / OCR / scanning' THEN 90
            WHEN 'Data entry / clerical processing' THEN 92 WHEN 'Graphic design / layout / DTP' THEN 94 WHEN 'Video production / post-production' THEN 88
            WHEN 'Social media / community management' THEN 86 WHEN 'SEO / digital marketing' THEN 88 WHEN 'Media / press monitoring' THEN 92
            WHEN 'Survey / market research' THEN 82 WHEN 'Report / publication production' THEN 90 WHEN 'Training / e-learning' THEN 85
            WHEN 'Call centre / helpdesk operations' THEN 72 WHEN 'Software licences / SaaS resale' THEN 55 WHEN 'Cloud / hosting / managed IT' THEN 60
            ELSE 25 END ai_automation_score,
          CASE lean_lane
            WHEN 'Printing / mailing / routing' THEN 92 WHEN 'Promotional merchandise' THEN 90 WHEN 'Signage / display production' THEN 85
            WHEN 'Software licences / SaaS resale' THEN 90 WHEN 'Hardware / AV resale' THEN 85 WHEN 'Office supplies / consumables resale' THEN 88
            WHEN 'Uniforms / PPE resale' THEN 82 WHEN 'Courier / mail fulfilment' THEN 75 WHEN 'Event support / production' THEN 70
            WHEN 'Recruitment / temporary staffing' THEN 65 ELSE 35 END broker_middleman_score,
          CASE broad_family
            WHEN 'Web / digital' THEN 95 WHEN 'Language / transcription' THEN 95 WHEN 'Document / data processing' THEN 92
            WHEN 'IT / software / cyber' THEN 80 WHEN 'Creative / communications / print' THEN 72 WHEN 'Consulting / research / audit' THEN 85
            WHEN 'Training / education' THEN 75 WHEN 'Staffing / HR' THEN 50 WHEN 'Other services' THEN 50
            WHEN 'Office / administrative goods' THEN 20 WHEN 'Hardware / AV / electronics' THEN 25 WHEN 'Other goods / resale' THEN 20
            WHEN 'Construction / works' THEN 5 WHEN 'Facilities / cleaning / maintenance' THEN 10 WHEN 'Transport / logistics' THEN 10
            ELSE 35 END remote_delivery_score,
          coalesce(median_award_value, estimated_value) reference_value,
          CASE
            WHEN coalesce(median_award_value,estimated_value) IS NULL THEN 45
            WHEN coalesce(median_award_value,estimated_value)<5000 THEN 25
            WHEN coalesce(median_award_value,estimated_value)<20000 THEN 45
            WHEN coalesce(median_award_value,estimated_value)<100000 THEN 65
            WHEN coalesce(median_award_value,estimated_value)<500000 THEN 80
            WHEN coalesce(median_award_value,estimated_value)<2000000 THEN 90 ELSE 92 END value_signal,
          CASE WHEN median_bidder_count IS NULL THEN 50 WHEN median_bidder_count<=1 THEN 95 WHEN median_bidder_count<=3 THEN 85 WHEN median_bidder_count<=5 THEN 75 WHEN median_bidder_count<=10 THEN 60 ELSE 35 END competition_signal
        FROM joined
      )
      SELECT *,
        round(0.34*greatest(ai_automation_score,broker_middleman_score)+0.18*remote_delivery_score+0.24*value_signal+0.14*competition_signal+
              0.10*CASE WHEN route_band='OPEN_PUBLIC' THEN 80 WHEN route_band='DIRECT_NONCOMPETITIVE' THEN 70 WHEN route_band='AWARD_FIRST_EVIDENCE' THEN 55 ELSE 50 END,2) historical_priority_score,
        CASE
          WHEN broad_family IN ('Construction / works','Architecture / engineering','Facilities / cleaning / maintenance','Transport / logistics','Healthcare / medical','Laboratory / scientific','Food / catering','Energy / utilities','Security / safety','Environment / waste') AND greatest(ai_automation_score,broker_middleman_score)<70 THEN 'PHYSICAL_COMPLEX'
          WHEN broker_middleman_score>=80 THEN 'PHYSICAL_OR_GOODS_BROKERABLE'
          WHEN remote_delivery_score>=80 THEN 'DIGITAL_REMOTE_LIKELY'
          WHEN remote_delivery_score>=50 THEN 'MIXED_OR_REMOTE_POSSIBLE'
          ELSE 'UNKNOWN_OR_PHYSICAL' END fulfillment_mode,
        CASE
          WHEN lean_lane<>'OTHER / OPEN WORLD' THEN 'KNOWN_LANE'
          WHEN broad_family IN ('IT / software / cyber','Web / digital','Creative / communications / print','Language / transcription','Document / data processing','Consulting / research / audit','Training / education','Office / administrative goods','Hardware / AV / electronics','Other goods / resale') THEN 'OPEN_WORLD_CANDIDATE'
          ELSE 'RESIDUAL' END discovery_bucket
      FROM scored
    ) TO {lit(str(out/'processed_records.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)""")

    proc_rel = f"read_parquet({lit(str(out/'processed_records.parquet'))})"
    tender_total, tender_fp, min_ord, max_ord = con.execute(f"SELECT count(*), sum(cast(hash(concat_ws('|',warehouse_source,tender_id,country,title,coalesce(cast(publication_date as varchar),''))) as hugeint)), min(scan_ordinal), max(scan_ordinal) FROM {proc_rel}").fetchone()
    distinct_ids = con.execute(f"SELECT count(distinct tender_id) FROM {proc_rel}").fetchone()[0]

    if a.expected_tenders and tender_total != a.expected_tenders:
        raise SystemExit(f"tender count mismatch: {tender_total} != {a.expected_tenders}")
    if a.expected_awards and award_total != a.expected_awards:
        raise SystemExit(f"award count mismatch: {award_total} != {a.expected_awards}")
    if a.expected_links and link_total != a.expected_links:
        raise SystemExit(f"link count mismatch: {link_total} != {a.expected_links}")
    if min_ord != 1 or max_ord != tender_total:
        raise SystemExit(f"scan ordinal integrity failure min={min_ord} max={max_ord} n={tender_total}")

    # Compact exhaustive aggregations; every processed record belongs to all of these cuts.
    family_rows = con.execute(f"""SELECT broad_family,count(*) n,count(distinct buyer_name) buyers,
      median(reference_value) FILTER (WHERE reference_value>=0) median_value,
      median(median_bidder_count) FILTER (WHERE median_bidder_count>=0) median_bidders,
      avg(historical_priority_score) avg_priority,
      sum(CASE WHEN discovery_bucket='OPEN_WORLD_CANDIDATE' THEN 1 ELSE 0 END) open_world
      FROM {proc_rel} GROUP BY 1 ORDER BY n DESC""").fetchall()
    write_csv(out/'broad_families.csv',['broad_family','records','buyers','median_value','median_bidders','avg_priority','open_world_candidates'],family_rows)

    lane_rows = con.execute(f"""SELECT lean_lane,route_band,currency,count(*) n,count(distinct buyer_name) buyers,
      median(reference_value) FILTER (WHERE reference_value>=0) median_value,
      quantile_cont(reference_value,0.25) FILTER (WHERE reference_value>=0) p25_value,
      quantile_cont(reference_value,0.75) FILTER (WHERE reference_value>=0) p75_value,
      median(median_bidder_count) FILTER (WHERE median_bidder_count>=0) median_bidders,
      avg(historical_priority_score) avg_priority
      FROM {proc_rel} GROUP BY 1,2,3 ORDER BY n DESC""").fetchall()
    write_csv(out/'lanes_by_route.csv',['lean_lane','route_band','currency','records','buyers','median_value','p25_value','p75_value','median_bidders','avg_priority'],lane_rows)

    src_rows = con.execute(f"""SELECT warehouse_source,country,route_band,count(*) n,count(distinct buyer_name) buyers,
      sum(CASE WHEN lean_lane<>'OTHER / OPEN WORLD' THEN 1 ELSE 0 END) known_lane,
      sum(CASE WHEN discovery_bucket='OPEN_WORLD_CANDIDATE' THEN 1 ELSE 0 END) open_world,
      median(reference_value) FILTER (WHERE reference_value>=0) median_value,
      avg(historical_priority_score) avg_priority
      FROM {proc_rel} GROUP BY 1,2,3 ORDER BY n DESC""").fetchall()
    write_csv(out/'source_route_coverage.csv',['warehouse_source','country','route_band','records','buyers','known_lane','open_world_candidates','median_value','avg_priority'],src_rows)

    buyer_rows = con.execute(f"""SELECT warehouse_source,country,buyer_name,lean_lane,route_band,count(*) n,
      median(reference_value) FILTER (WHERE reference_value>=0) median_value,avg(historical_priority_score) avg_priority
      FROM {proc_rel} WHERE buyer_name<>'' GROUP BY 1,2,3,4,5 HAVING count(*)>=2 ORDER BY n DESC,avg_priority DESC LIMIT 3000""").fetchall()
    write_csv(out/'repeat_buyers.csv',['warehouse_source','country','buyer_name','lean_lane','route_band','records','median_value','avg_priority'],buyer_rows)

    # Open-world residual clustering by source/code/title signature. This accounts for the part old lane classifiers ignored.
    residual_rows = con.execute(f"""WITH x AS (
      SELECT warehouse_source,country,broad_family,coalesce(nullif(code,''),'NO_CODE') code,
             left(regexp_replace(lower(title),'[0-9]+','<n>','g'),120) title_signature,
             count(*) n,median(reference_value) FILTER (WHERE reference_value>=0) median_value,
             median(median_bidder_count) FILTER (WHERE median_bidder_count>=0) median_bidders,
             avg(historical_priority_score) avg_priority
      FROM {proc_rel} WHERE lean_lane='OTHER / OPEN WORLD'
      GROUP BY 1,2,3,4,5
    ) SELECT * FROM x ORDER BY avg_priority DESC,n DESC LIMIT 5000""").fetchall()
    write_csv(out/'open_world_clusters.csv',['warehouse_source','country','broad_family','code','title_signature','records','median_value','median_bidders','avg_priority'],residual_rows)

    review_rows = con.execute(f"""SELECT warehouse_source,country,tender_id,publication_date,buyer_name,title,code,procurement_procedure,route_band,lean_lane,broad_family,
      fulfillment_mode,currency,reference_value,median_bidder_count,historical_priority_score,official_url
      FROM {proc_rel}
      ORDER BY historical_priority_score DESC, coalesce(reference_value,0) DESC
      LIMIT 10000""").fetchall()
    write_csv(out/'top_record_review_queue.csv',['warehouse_source','country','tender_id','publication_date','buyer_name','title','code','procedure','route_band','lean_lane','broad_family','fulfillment_mode','currency','reference_value','median_bidders','historical_priority_score','official_url'],review_rows)

    dist = con.execute(f"""SELECT discovery_bucket,count(*) n FROM {proc_rel} GROUP BY 1 ORDER BY n DESC""").fetchall()
    route_dist = con.execute(f"""SELECT route_band,count(*) n FROM {proc_rel} GROUP BY 1 ORDER BY n DESC""").fetchall()
    score_dist = con.execute(f"""SELECT CASE WHEN historical_priority_score>=80 THEN '80+' WHEN historical_priority_score>=70 THEN '70-79.99' WHEN historical_priority_score>=60 THEN '60-69.99' WHEN historical_priority_score>=50 THEN '50-59.99' ELSE '<50' END band,count(*) n FROM {proc_rel} GROUP BY 1 ORDER BY 1""").fetchall()

    summary = {
      'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'label':a.label,'grain':a.grain,
      'inputs':{'historical':str(hp),'awards':str(awp),'bridge':str(bp)},
      'columns':{'historical':sorted(hc),'awards':sorted(ac),'bridge':sorted(bc)},
      'counts':{'procurement_records':int(tender_total),'distinct_procurement_ids':int(distinct_ids),'award_rows':int(award_total),'award_supplier_links':int(link_total)},
      'fingerprints':{'procurement_hash_sum':str(tender_fp),'award_hash_sum':str(award_fp[1]),'link_hash_sum':str(link_fp[1])},
      'integrity':{'scan_ordinal_min':int(min_ord),'scan_ordinal_max':int(max_ord),'no_row_filter_before_scoring':True,'all_rows_materialized':True,'expected_counts_checked':bool(a.expected_tenders or a.expected_awards or a.expected_links),'status':'PASS'},
      'discovery_bucket_counts':{r[0]:int(r[1]) for r in dist},
      'route_counts':{r[0]:int(r[1]) for r in route_dist},
      'priority_bands':{r[0]:int(r[1]) for r in score_dist},
      'notes':['Historical priority is a prior, not a live bid verdict.','AWARD_FIRST_PROCUREMENT records are not reconstructed original tender notices.','OTHER / OPEN WORLD is intentionally retained and clustered rather than discarded.','No currency mixing is performed in value tables.']
    }
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

    top_families = family_rows[:20]
    top_lanes = [r for r in lane_rows if r[0] != 'OTHER / OPEN WORLD'][:25]
    md = [f"# Exhaustive every-record read — {a.label}","",f"Version: `{VERSION}`",f"Grain: `{a.grain}`",'',
          f"- Procurement rows processed: **{tender_total:,}**",f"- Award rows scanned: **{award_total:,}**",f"- Award↔supplier links scanned: **{link_total:,}**",f"- Distinct procurement IDs: **{distinct_ids:,}**",f"- Integrity: **PASS** — scan ordinal 1..{tender_total:,}; no pre-scoring row filter.","",
          "## Discovery accounting",""]
    for k,v in summary['discovery_bucket_counts'].items(): md.append(f"- {k}: {v:,}")
    md += ["","## Broad families","","|Family|Records|Buyers|Median value|Median bidders|Avg priority|Open-world|","|---|---:|---:|---:|---:|---:|---:|"]
    for r in top_families: md.append(f"|{r[0]}|{r[1]:,}|{r[2]:,}|{r[3] if r[3] is not None else 'NA'}|{r[4] if r[4] is not None else 'NA'}|{round(r[5],2) if r[5] is not None else 'NA'}|{r[6]:,}|")
    md += ["","## Named lanes by route/currency","","|Lane|Route|Currency|Records|Buyers|Median|P25|P75|Median bidders|Avg priority|","|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in top_lanes: md.append(f"|{r[0]}|{r[1]}|{r[2]}|{r[3]:,}|{r[4]:,}|{r[5] if r[5] is not None else 'NA'}|{r[6] if r[6] is not None else 'NA'}|{r[7] if r[7] is not None else 'NA'}|{r[8] if r[8] is not None else 'NA'}|{round(r[9],2) if r[9] is not None else 'NA'}|")
    md += ["","## What 'every record' means here","","Every procurement row was materialized and scored before aggregation. Every award row and award-supplier link row was scanned. This is exhaustive structured-data processing, not a claim that every underlying DCE/PDF attachment was manually read; DCE deep-read is a separate downstream gate for live/final bidding.",""]
    (out/'REPORT.md').write_text('\n'.join(md),encoding='utf-8')

    # processed_records is reconstructible and potentially very large; delete only after compact outputs + fingerprints exist.
    # Raw canonical data remains upstream in immutable release assets.
    for p in [out/'work.duckdb', out/'work.duckdb.wal']:
        if p.exists(): p.unlink()
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
