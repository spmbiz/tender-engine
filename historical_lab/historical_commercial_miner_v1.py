#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from pipeline.exhaustive_record_reader_v1 import (
    choose,
    cols_for,
    date_expr,
    double_expr,
    lit,
    qi,
    relation,
    route_case,
    text_expr,
)

VERSION = "SPM_HISTORICAL_COMMERCIAL_MINER_V1"


def write_csv(path: Path, header: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--grain", required=True, choices=["NOTICE_FIRST_TENDER", "AWARD_FIRST_PROCUREMENT"])
    ap.add_argument("--historical", required=True)
    ap.add_argument("--awards", required=True)
    ap.add_argument("--bridge", required=True)
    ap.add_argument("--expected-tenders", type=int, required=True)
    ap.add_argument("--expected-awards", type=int, required=True)
    ap.add_argument("--expected-links", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ducktmp").mkdir(exist_ok=True)

    con = duckdb.connect(str(out / "work.duckdb"))
    con.execute("SET memory_limit='5GB'")
    con.execute(f"SET temp_directory={lit(str(out/'ducktmp'))}")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")

    hrel = relation(Path(a.historical))
    arel = relation(Path(a.awards))
    brel = relation(Path(a.bridge))
    hc, ac, bc = cols_for(con, hrel), cols_for(con, arel), cols_for(con, brel)

    hid = choose(hc, "Tender_ID", "Procurement_ID", "Contract_ID", "tender_id", "id")
    hsource = choose(hc, "Source", "Warehouse_Source", "source")
    hcountry = choose(hc, "Country", "country")
    htitle = choose(hc, "Title", "Contract_Title", "Description", "title")
    hscope = choose(hc, "Scope_Summary", "Description", "Scope", "description")
    hbuyer = choose(hc, "Buyer_Name", "Contracting_Authority", "Awarding_Agency", "Agency_Name", "buyer_name")
    hbuyerid = choose(hc, "Buyer_ID", "Agency_ID", "buyer_id")
    hcur = choose(hc, "Currency", "currency")
    hest = choose(hc, "Estimated_Value", "Contract_Value", "Award_Value", "Total_Obligation", "value")
    hpub = choose(hc, "Publication_Date", "Award_Date", "Action_Date", "date")
    hcode = choose(hc, "CPV", "CPV_Code", "NAICS", "NAICS_Code", "PSC", "PSC_Code", "Category_Code", "code")
    hcoded = choose(hc, "CPV_Description", "NAICS_Description", "PSC_Description", "Category", "Subcategory", "code_description")
    hproc = choose(hc, "Procurement_Procedure", "Procedure", "Procedure_Type", "procurement_procedure")

    aid = choose(ac, "Award_ID", "Contract_ID", "award_id", "id")
    atid = choose(ac, "Tender_ID", "Procurement_ID", "tender_id")
    aval = choose(ac, "Award_Value", "Contract_Value", "Total_Obligation", "value")
    acur = choose(ac, "Currency", "currency")
    abid = choose(ac, "Bidder_Count", "Tenderer_Count", "Number_Of_Bids", "bidder_count")
    adate = choose(ac, "Award_Date", "Action_Date", "Contract_Start_Date", "date")

    baid = choose(bc, "Award_ID", "Contract_ID", "award_id")
    bsid = choose(bc, "Supplier_ID", "Recipient_ID", "supplier_id")
    bsname = choose(bc, "Supplier_Name", "Recipient_Name", "supplier_name")

    if not hid:
        raise SystemExit(json.dumps({"error": "missing stable procurement id", "columns": sorted(hc)}, indent=2))

    source = text_expr(hsource, lit(a.label)) if hsource else lit(a.label)
    country = text_expr(hcountry, lit(a.label)) if hcountry else lit(a.label)
    tid = text_expr(hid)
    title = text_expr(htitle)
    scope = text_expr(hscope)
    buyer = text_expr(hbuyer)
    buyerid = text_expr(hbuyerid)
    cur = f"upper(coalesce(nullif({text_expr(hcur)},''),'UNKNOWN'))" if hcur else "'UNKNOWN'"
    est = double_expr(hest)
    pub = date_expr(hpub)
    code = text_expr(hcode)
    coded = text_expr(hcoded)
    proc = text_expr(hproc, "'UNKNOWN'")
    route = route_case(source, proc, a.grain)

    award_total = con.execute(f"SELECT count(*) FROM {arel}").fetchone()[0]
    link_total = con.execute(f"SELECT count(*) FROM {brel}").fetchone()[0]
    if award_total != a.expected_awards:
        raise SystemExit(f"award count mismatch {award_total} != {a.expected_awards}")
    if link_total != a.expected_links:
        raise SystemExit(f"supplier-link count mismatch {link_total} != {a.expected_links}")

    award_key = text_expr(aid) if aid else "''"
    award_tender = text_expr(atid) if atid else "''"
    award_value = double_expr(aval)
    award_cur = f"upper(coalesce(nullif({text_expr(acur)},''),'UNKNOWN'))" if acur else "'UNKNOWN'"
    award_bid = double_expr(abid)
    award_date = date_expr(adate)

    if atid:
        con.execute(f"""
        CREATE TABLE award_stats AS
        SELECT {award_tender} tender_id,
               count(*) award_rows,
               quantile_cont({award_value},0.25) FILTER (WHERE {award_value} IS NOT NULL AND {award_value}>=0) p25_award_value,
               median({award_value}) FILTER (WHERE {award_value} IS NOT NULL AND {award_value}>=0) median_award_value,
               quantile_cont({award_value},0.75) FILTER (WHERE {award_value} IS NOT NULL AND {award_value}>=0) p75_award_value,
               median({award_bid}) FILTER (WHERE {award_bid} IS NOT NULL AND {award_bid}>=0) median_bidder_count,
               max({award_cur}) FILTER (WHERE {award_cur}<>'UNKNOWN') award_currency,
               max({award_date}) max_award_date
        FROM {arel}
        GROUP BY 1
        """)
    else:
        con.execute("CREATE TABLE award_stats(tender_id varchar, award_rows bigint, p25_award_value double, median_award_value double, p75_award_value double, median_bidder_count double, award_currency varchar, max_award_date date)")

    # Fractional supplier weights prevent consortium/multi-supplier awards from being double-counted.
    if baid and aid and atid:
        link_award = text_expr(baid)
        link_sid = text_expr(bsid) if bsid else "''"
        link_name = text_expr(bsname) if bsname else "''"
        con.execute(f"""
        CREATE TABLE tender_suppliers AS
        WITH aw AS (
          SELECT {award_key} award_id, {award_tender} tender_id FROM {arel}
        ), br0 AS (
          SELECT {link_award} award_id,
                 coalesce(nullif({link_sid},''), nullif({link_name},''), 'UNKNOWN_SUPPLIER') supplier_id,
                 coalesce(nullif({link_name},''), nullif({link_sid},''), 'UNKNOWN_SUPPLIER') supplier_name
          FROM {brel}
        ), br AS (
          SELECT *, count(*) over(partition by award_id) suppliers_on_award FROM br0
        )
        SELECT aw.tender_id, br.supplier_id, br.supplier_name,
               CASE WHEN br.suppliers_on_award>0 THEN 1.0/br.suppliers_on_award ELSE NULL END supplier_weight
        FROM aw JOIN br USING(award_id)
        """)
    else:
        con.execute("CREATE TABLE tender_suppliers(tender_id varchar, supplier_id varchar, supplier_name varchar, supplier_weight double)")

    # The signature is intentionally ontology-free: native code + normalized recurring title/scope wording.
    raw_text = f"lower(concat_ws(' ',{title},{scope},{coded}))"
    normalized = (
        "trim(regexp_replace(regexp_replace(regexp_replace(" + raw_text + ","
        "'[0-9]{2,}',' <n> ','g'),"
        "'[^a-zà-ÿ0-9<>]+',' ','g'),"
        "'\\b(request for|request to|invitation to|invitation for|tender for|tender to|procurement of|provision of|supply of|services for|services of|contract for|framework agreement for|accord cadre|marché de|marche de|prestations de|fourniture de|fourniture et livraison de|appel d offres|avis de marché|avis de marche|public contract|auftrag über|auftrag uber|vergabeverfahren|ausschreibung)\\b',' ','g'))"
    )
    sig = f"left(regexp_replace({normalized},'\\s+',' ','g'),180)"

    con.execute(f"""
    CREATE TABLE proc AS
    WITH base AS (
      SELECT {source} warehouse_source, {tid} tender_id, {country} country,
             {buyerid} buyer_id, {buyer} buyer_name, {cur} currency,
             {est} estimated_value, {pub} publication_date, {title} title, {scope} scope_summary,
             coalesce(nullif({code},''),'NO_CODE') native_code,
             {coded} code_description, {proc} procurement_procedure, {route} route_band,
             {sig} phrase_signature,
             row_number() over() scan_ordinal
      FROM {hrel}
    )
    SELECT b.*, a.award_rows, a.p25_award_value, a.median_award_value, a.p75_award_value,
           a.median_bidder_count, coalesce(a.award_currency,'UNKNOWN') award_currency,
           coalesce(a.median_award_value,b.estimated_value) reference_value,
           hash(concat_ws('|',b.country,b.currency,b.route_band,b.native_code,b.phrase_signature)) cluster_id
    FROM base b LEFT JOIN award_stats a USING(tender_id)
    """)

    tender_total, min_ord, max_ord, distinct_ids = con.execute(
        "SELECT count(*),min(scan_ordinal),max(scan_ordinal),count(distinct tender_id) FROM proc"
    ).fetchone()
    if tender_total != a.expected_tenders:
        raise SystemExit(f"procurement count mismatch {tender_total} != {a.expected_tenders}")
    if min_ord != 1 or max_ord != tender_total:
        raise SystemExit(f"ordinal integrity failure {min_ord}..{max_ord} n={tender_total}")

    con.execute("""
    CREATE TABLE cluster_base AS
    SELECT cluster_id, warehouse_source, country, currency, route_band, native_code,
           any_value(code_description) code_description,
           phrase_signature,
           count(*) records,
           count(distinct nullif(buyer_name,'')) buyers,
           quantile_cont(reference_value,0.25) FILTER (WHERE reference_value IS NOT NULL AND reference_value>=0) p25_value,
           median(reference_value) FILTER (WHERE reference_value IS NOT NULL AND reference_value>=0) median_value,
           quantile_cont(reference_value,0.75) FILTER (WHERE reference_value IS NOT NULL AND reference_value>=0) p75_value,
           median(median_bidder_count) FILTER (WHERE median_bidder_count IS NOT NULL AND median_bidder_count>=0) median_bidders,
           min(publication_date) first_date,
           max(publication_date) last_date
    FROM proc
    GROUP BY 1,2,3,4,5,6,8
    """)

    con.execute("""
    CREATE TABLE buyer_cluster AS
    SELECT cluster_id,buyer_name,count(*) records,
           median(reference_value) FILTER (WHERE reference_value IS NOT NULL AND reference_value>=0) median_value
    FROM proc WHERE buyer_name<>'' GROUP BY 1,2
    """)
    con.execute("""
    CREATE TABLE buyer_stats AS
    SELECT cluster_id,
           count(*) FILTER (WHERE records>=2) repeat_buyers,
           max(records) top_buyer_records,
           sum(records) buyer_named_records
    FROM buyer_cluster GROUP BY 1
    """)

    con.execute("""
    CREATE TABLE supplier_cluster AS
    SELECT p.cluster_id,ts.supplier_id,any_value(ts.supplier_name) supplier_name,
           sum(ts.supplier_weight) weighted_awards
    FROM proc p JOIN tender_suppliers ts USING(tender_id)
    WHERE ts.supplier_id<>'UNKNOWN_SUPPLIER'
    GROUP BY 1,2
    """)
    con.execute("""
    CREATE TABLE supplier_stats AS
    SELECT cluster_id,
           count(*) suppliers,
           max(weighted_awards) top_supplier_weight,
           sum(weighted_awards) total_supplier_weight,
           CASE WHEN sum(weighted_awards)>0 THEN max(weighted_awards)/sum(weighted_awards) END top_supplier_share
    FROM supplier_cluster GROUP BY 1
    """)

    con.execute("""
    CREATE TABLE scored_clusters AS
    WITH x AS (
      SELECT c.*, coalesce(b.repeat_buyers,0) repeat_buyers,
             b.top_buyer_records,b.buyer_named_records,
             s.suppliers,s.top_supplier_share,
             percent_rank() over(partition by c.country,c.currency order by c.records) pr_volume,
             percent_rank() over(partition by c.country,c.currency order by c.buyers) pr_buyers,
             percent_rank() over(partition by c.country,c.currency order by c.median_value nulls first) pr_value,
             percent_rank() over(partition by c.country,c.currency order by c.median_bidders nulls last) pr_bidders,
             percent_rank() over(partition by c.country,c.currency order by s.top_supplier_share nulls last) pr_concentration
      FROM cluster_base c
      LEFT JOIN buyer_stats b USING(cluster_id)
      LEFT JOIN supplier_stats s USING(cluster_id)
    )
    SELECT *,
      round(100*(0.24*pr_volume + 0.22*pr_buyers + 0.20*coalesce(pr_value,0.5)
                 +0.17*(1-coalesce(pr_bidders,0.5)) +0.17*(1-coalesce(pr_concentration,0.5))),2) market_structure_signal,
      CASE
        WHEN records>=20 AND buyers>=5 AND repeat_buyers>=2 THEN 'MULTI_BUYER_REPEAT_MARKET'
        WHEN records>=10 AND buyers>=3 THEN 'MULTI_BUYER_MARKET'
        WHEN records>=5 AND repeat_buyers>=1 THEN 'REPEAT_BUYER_NICHE'
        WHEN records>=3 THEN 'RECURRING_NICHE'
        ELSE 'SPARSE_OR_ONE_OFF'
      END recurrence_shape
    FROM x
    """)

    # Full-accounting code census: no semantic assumptions, currencies kept separate.
    code_rows = con.execute("""
    SELECT warehouse_source,country,currency,route_band,native_code,
           any_value(code_description) code_description,
           count(*) records,count(distinct nullif(buyer_name,'')) buyers,
           quantile_cont(reference_value,0.25) FILTER (WHERE reference_value>=0) p25_value,
           median(reference_value) FILTER (WHERE reference_value>=0) median_value,
           quantile_cont(reference_value,0.75) FILTER (WHERE reference_value>=0) p75_value,
           median(median_bidder_count) FILTER (WHERE median_bidder_count>=0) median_bidders
    FROM proc GROUP BY 1,2,3,4,5 ORDER BY records DESC
    """).fetchall()
    write_csv(out/"native_code_market.csv",
              ["warehouse_source","country","currency","route_band","native_code","code_description","records","buyers","p25_value","median_value","p75_value","median_bidders"],
              code_rows)

    high_rows = con.execute("""
    SELECT warehouse_source,country,currency,route_band,native_code,code_description,phrase_signature,
           records,buyers,repeat_buyers,p25_value,median_value,p75_value,median_bidders,suppliers,top_supplier_share,
           recurrence_shape,market_structure_signal,first_date,last_date
    FROM scored_clusters
    WHERE records>=3
    ORDER BY market_structure_signal DESC,records DESC
    LIMIT 12000
    """).fetchall()
    write_csv(out/"high_signal_clusters.csv",
              ["warehouse_source","country","currency","route_band","native_code","code_description","phrase_signature","records","buyers","repeat_buyers","p25_value","median_value","p75_value","median_bidders","suppliers","top_supplier_share","recurrence_shape","market_structure_signal","first_date","last_date"],
              high_rows)

    buyer_rows = con.execute("""
    SELECT s.warehouse_source,s.country,s.currency,s.route_band,s.native_code,s.phrase_signature,
           b.buyer_name,b.records,b.median_value,s.market_structure_signal
    FROM buyer_cluster b JOIN scored_clusters s USING(cluster_id)
    WHERE b.records>=2
    ORDER BY b.records DESC,s.market_structure_signal DESC
    LIMIT 12000
    """).fetchall()
    write_csv(out/"repeat_buyer_cluster_matrix.csv",
              ["warehouse_source","country","currency","route_band","native_code","phrase_signature","buyer_name","records","median_value","market_structure_signal"],
              buyer_rows)

    supplier_rows = con.execute("""
    SELECT s.warehouse_source,s.country,s.currency,s.route_band,s.native_code,s.phrase_signature,
           w.supplier_name,w.weighted_awards,s.top_supplier_share,s.market_structure_signal
    FROM supplier_cluster w JOIN scored_clusters s USING(cluster_id)
    ORDER BY w.weighted_awards DESC,s.market_structure_signal DESC
    LIMIT 12000
    """).fetchall()
    write_csv(out/"winner_cluster_matrix.csv",
              ["warehouse_source","country","currency","route_band","native_code","phrase_signature","supplier_name","weighted_awards","cluster_top_supplier_share","market_structure_signal"],
              supplier_rows)

    example_rows = con.execute("""
    WITH ranked AS (
      SELECT p.cluster_id,p.tender_id,p.publication_date,p.buyer_name,p.title,p.reference_value,p.median_bidder_count,
             row_number() over(partition by p.cluster_id order by p.reference_value desc nulls last,p.publication_date desc nulls last) rn
      FROM proc p JOIN scored_clusters s USING(cluster_id)
      WHERE s.records>=3
    )
    SELECT s.warehouse_source,s.country,s.currency,s.route_band,s.native_code,s.phrase_signature,
           r.tender_id,r.publication_date,r.buyer_name,r.title,r.reference_value,r.median_bidder_count,s.market_structure_signal
    FROM ranked r JOIN scored_clusters s USING(cluster_id)
    WHERE r.rn<=3
    ORDER BY s.market_structure_signal DESC,s.records DESC,r.rn
    LIMIT 30000
    """).fetchall()
    write_csv(out/"cluster_examples.csv",
              ["warehouse_source","country","currency","route_band","native_code","phrase_signature","tender_id","publication_date","buyer_name","title","reference_value","median_bidder_count","market_structure_signal"],
              example_rows)

    total_clusters, recurring_clusters, multi_buyer_repeat, singleton_clusters = con.execute("""
    SELECT count(*),
           count(*) FILTER (WHERE records>=3),
           count(*) FILTER (WHERE records>=20 AND buyers>=5 AND repeat_buyers>=2),
           count(*) FILTER (WHERE records=1)
    FROM scored_clusters
    """).fetchone()

    summary = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": a.label,
        "grain": a.grain,
        "counts": {
            "procurement_records_scanned": tender_total,
            "distinct_procurement_ids": distinct_ids,
            "award_rows_scanned": award_total,
            "award_supplier_links_scanned": link_total,
            "commercial_clusters": total_clusters,
            "clusters_with_3plus_records": recurring_clusters,
            "multi_buyer_repeat_markets": multi_buyer_repeat,
            "singleton_clusters": singleton_clusters,
        },
        "integrity": {
            "expected_tenders": a.expected_tenders,
            "scan_ordinal_min": min_ord,
            "scan_ordinal_max": max_ord,
            "status": "PASS",
        },
        "method": {
            "ontology_free_cluster_key": "country + currency + route + native code + normalized title/scope signature",
            "supplier_weights": "fractionalized per award when multiple supplier links exist",
            "currency_rule": "percentile scoring partitioned by country and currency; no FX mixing",
            "score_role": "market-structure triage only; not SPM feasibility and not live eligibility",
        },
    }
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")

    report = [
        f"# Historical Commercial Miner — {a.label}", "",
        "**STATUS: PASS**", "",
        f"- Grain: `{a.grain}`",
        f"- Procurement records scanned: **{tender_total:,}**",
        f"- Award rows scanned: **{award_total:,}**",
        f"- Award↔supplier links scanned: **{link_total:,}**",
        f"- Commercial clusters: **{total_clusters:,}**",
        f"- Clusters with ≥3 records: **{recurring_clusters:,}**",
        f"- Multi-buyer repeat markets: **{multi_buyer_repeat:,}**", "",
        "## Interpretation", "",
        "This pass is deliberately ontology-free at the clustering layer. It discovers recurring market structure from native codes and normalized procurement wording before SPM feasibility is applied.",
        "Market-structure signal is a within-country/currency percentile blend of recurrence, buyer breadth, value, bidder evidence, and supplier concentration. It is triage only.",
        "USAspending and AusTender remain award-first evidence. Historical structure never proves that a current tender is open or that SPM is eligible.", "",
        "## Outputs", "",
        "- `native_code_market.csv`: exhaustive native-code census by route/currency.",
        "- `high_signal_clusters.csv`: top recurring empirical title/code cohorts.",
        "- `repeat_buyer_cluster_matrix.csv`: repeat buyers inside those cohorts.",
        "- `winner_cluster_matrix.csv`: historical supplier/winner structure with fractional consortium weights.",
        "- `cluster_examples.csv`: representative procurements for semantic QA.", "",
    ]
    (out/"REPORT.md").write_text("\n".join(report),encoding="utf-8")

    con.close()


if __name__ == "__main__":
    main()
