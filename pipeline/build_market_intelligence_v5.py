#!/usr/bin/env python3
from __future__ import annotations

"""
Build SPM-oriented historical procurement intelligence from Global Core v4.

Goals
-----
- rank actionable micro-niches without mixing currencies;
- separate source facts from derived heuristics;
- preserve notice-first vs award-first evidence lanes;
- quantify buyer recurrence, supplier fragmentation, bidder evidence,
  price bands, seasonality, winner archetypes, and representative examples;
- produce compact outputs suitable for GPT/Drive review.

This script never establishes tender eligibility or a live bid verdict.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

VERSION = "SPM_MARKET_INTELLIGENCE_V5"
SOURCE_RELEASE = "tender-normalized-global-core-v4"


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def choose(cols: set[str], *candidates: str) -> str | None:
    by_lower = {c.casefold(): c for c in cols}
    for cand in candidates:
        if cand.casefold() in by_lower:
            return by_lower[cand.casefold()]
    return None


def safe_text(col: str | None, fallback_sql: str = "''") -> str:
    return f"trim(cast({qident(col)} as varchar))" if col else fallback_sql


def cpv4_expr(col: str | None) -> str:
    if not col:
        return "''"
    return f"regexp_extract(cast({qident(col)} as varchar), '[0-9]{{4}}', 0)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical", required=True)
    ap.add_argument("--awards", required=True)
    ap.add_argument("--award-suppliers", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hist = Path(args.historical)
    awards = Path(args.awards)
    bridge = Path(args.award_suppliers)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in (hist, awards, bridge):
        if not p.is_file() or p.stat().st_size == 0:
            raise SystemExit(f"missing_or_empty:{p}")

    con = duckdb.connect(database=":memory:")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")

    hdesc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(hist)]).fetchall()
    adesc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(awards)]).fetchall()
    bdesc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(bridge)]).fetchall()
    hcols = {r[0] for r in hdesc}
    acols = {r[0] for r in adesc}
    bcols = {r[0] for r in bdesc}

    h_source = choose(hcols, "Warehouse_Source", "source", "source_name", "portal", "lane")
    h_tid = choose(hcols, "Historical_Tender_ID", "record_id", "source_record_id", "notice_id", "id")
    h_country = choose(hcols, "Country", "country_code", "Buyer_Country", "jurisdiction")
    h_buyer_id = choose(hcols, "Buyer_ID", "buyer_id")
    h_buyer_name = choose(hcols, "Buyer_Name", "buyer_name", "buyer", "contracting_authority")
    h_category = choose(hcols, "Category", "category")
    h_subcategory = choose(hcols, "Subcategory", "subcategory")
    h_currency = choose(hcols, "Currency", "currency")
    h_lean = choose(hcols, "Lean_Fit", "lean_fit")
    h_est = choose(hcols, "Official_Estimated_Value", "estimated_value", "value")
    h_pub = choose(hcols, "Publication_Date", "publication_date", "date")
    h_title = choose(hcols, "Title", "title", "Tender_Title", "notice_title")
    h_cpv = choose(hcols, "CPV", "cpv", "CPV_Code", "cpv_code", "main_cpv", "classification_id")
    h_url = choose(hcols, "Official_URL", "official_url", "Source_URL", "source_url", "url")
    h_evidence = choose(hcols, "Evidence_Confidence", "evidence_confidence", "Evidence_Grain", "evidence_grain")

    a_source = choose(acols, "Warehouse_Source", "source", "source_name", "portal", "lane")
    a_tid = choose(acols, "Historical_Tender_ID", "historical_tender_id", "record_id", "notice_id")
    a_award_id = choose(acols, "Award_ID", "award_id", "id")
    a_value = choose(acols, "Award_Value", "award_value", "value")
    a_currency = choose(acols, "Currency", "currency", "Award_Currency", "award_currency")
    a_bidder = choose(acols, "Bidder_Count", "bidder_count", "number_of_bids", "bids_received")
    a_supplier_id = choose(acols, "Supplier_ID", "supplier_id")
    a_date = choose(acols, "Award_Date", "award_date", "date")

    b_source = choose(bcols, "Warehouse_Source", "source", "source_name", "portal", "lane")
    b_award_id = choose(bcols, "Award_ID", "award_id")
    b_supplier_id = choose(bcols, "Supplier_ID", "supplier_id")
    b_supplier_name = choose(bcols, "Supplier_Name", "supplier_name", "winner_name", "name")
    b_alloc = choose(bcols, "Award_Value_Allocated", "award_value_allocated", "allocated_value")

    required = {
        "historical.source": h_source,
        "historical.tender_id": h_tid,
        "historical.buyer_name": h_buyer_name,
        "historical.category": h_category,
        "historical.subcategory": h_subcategory,
        "awards.source": a_source,
        "awards.tender_id": a_tid,
        "awards.award_id": a_award_id,
        "bridge.source": b_source,
        "bridge.award_id": b_award_id,
        "bridge.supplier_id": b_supplier_id,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SystemExit(json.dumps({
            "error": "missing_required_columns",
            "missing": missing,
            "historical_columns": sorted(hcols),
            "award_columns": sorted(acols),
            "bridge_columns": sorted(bcols),
        }, indent=2))

    source = safe_text(h_source)
    tid = safe_text(h_tid)
    country = f"upper({safe_text(h_country)})" if h_country else f"upper({source})"
    buyer_id = safe_text(h_buyer_id, "''")
    buyer_name = safe_text(h_buyer_name)
    buyer_key = f"lower(regexp_replace(coalesce(nullif({buyer_id},''),{buyer_name}), '\\s+', ' ', 'g'))"
    category = f"coalesce(nullif({safe_text(h_category)},''),'UNKNOWN')"
    subcategory = f"coalesce(nullif({safe_text(h_subcategory)},''),'UNKNOWN')"
    currency = f"upper(coalesce(nullif({safe_text(h_currency)},''),'UNKNOWN'))"
    lean = f"try_cast({qident(h_lean)} AS DOUBLE)" if h_lean else "NULL::DOUBLE"
    est = f"try_cast({qident(h_est)} AS DOUBLE)" if h_est else "NULL::DOUBLE"
    pubdate = f"try_cast({qident(h_pub)} AS DATE)" if h_pub else "NULL::DATE"
    title = safe_text(h_title, "''")
    cpv4 = cpv4_expr(h_cpv)
    url = safe_text(h_url, "''")
    evidence = safe_text(h_evidence, "'UNKNOWN'")

    asource = safe_text(a_source)
    atid = safe_text(a_tid)
    award_id = safe_text(a_award_id)
    aval = f"try_cast({qident(a_value)} AS DOUBLE)" if a_value else "NULL::DOUBLE"
    acurrency = f"upper(coalesce(nullif({safe_text(a_currency)},''),'UNKNOWN'))" if a_currency else "'UNKNOWN'"
    bidder = f"try_cast({qident(a_bidder)} AS DOUBLE)" if a_bidder else "NULL::DOUBLE"
    award_date = f"try_cast({qident(a_date)} AS DATE)" if a_date else "NULL::DATE"

    bsource = safe_text(b_source)
    baward = safe_text(b_award_id)
    bsupplier = safe_text(b_supplier_id)
    bsupplier_name = safe_text(b_supplier_name, "''")
    balloc = f"try_cast({qident(b_alloc)} AS DOUBLE)" if b_alloc else "NULL::DOUBLE"

    con.execute(f"""
        CREATE TEMP TABLE tend AS
        SELECT
            {source} AS warehouse_source,
            {tid} AS tender_id,
            {country} AS country,
            {buyer_key} AS buyer_key,
            {buyer_name} AS buyer_name,
            {category} AS category,
            {subcategory} AS subcategory,
            {currency} AS currency,
            {lean} AS lean_fit,
            {est} AS estimated_value,
            {pubdate} AS publication_date,
            {title} AS title,
            {cpv4} AS cpv4,
            {url} AS official_url,
            {evidence} AS evidence_confidence
        FROM read_parquet(?)
    """, [str(hist)])

    con.execute(f"""
        CREATE TEMP TABLE aw AS
        SELECT
            {asource} AS warehouse_source,
            {atid} AS tender_id,
            {award_id} AS award_id,
            {aval} AS award_value,
            {acurrency} AS award_currency,
            {bidder} AS bidder_count,
            {award_date} AS award_date
            {"," + safe_text(a_supplier_id) + " AS direct_supplier_id" if a_supplier_id else ""}
        FROM read_parquet(?)
    """, [str(awards)])

    con.execute(f"""
        CREATE TEMP TABLE br AS
        SELECT
            {bsource} AS warehouse_source,
            {baward} AS award_id,
            {bsupplier} AS supplier_id,
            {bsupplier_name} AS supplier_name,
            {balloc} AS award_value_allocated
        FROM read_parquet(?)
        WHERE nullif({bsupplier},'') IS NOT NULL
    """, [str(bridge)])

    counts = {
        "historical_tenders": con.execute("SELECT count(*) FROM tend").fetchone()[0],
        "awards": con.execute("SELECT count(*) FROM aw").fetchone()[0],
        "award_supplier_links": con.execute("SELECT count(*) FROM br").fetchone()[0],
    }

    con.execute("""
        CREATE TEMP TABLE buyer_niche AS
        SELECT warehouse_source,country,category,subcategory,currency,buyer_key,
               any_value(buyer_name) buyer_name,
               count(DISTINCT tender_id) tender_count,
               min(publication_date) first_publication_date,
               max(publication_date) last_publication_date,
               median(estimated_value) FILTER (WHERE estimated_value>1) median_estimated_value
        FROM tend
        WHERE buyer_key<>''
        GROUP BY 1,2,3,4,5,6
    """)
    con.execute(f"""
        COPY (
          SELECT *,
                 CASE WHEN tender_count>=20 THEN 'VERY_HIGH_REPEAT'
                      WHEN tender_count>=10 THEN 'HIGH_REPEAT'
                      WHEN tender_count>=5 THEN 'REPEAT'
                      WHEN tender_count>=3 THEN 'LIGHT_REPEAT'
                      ELSE 'ONE_OFF' END repeat_band,
                 'NOTICE_FIRST_DERIVED' evidence_type
          FROM buyer_niche
          WHERE tender_count>=3
          ORDER BY tender_count DESC
        ) TO '{(out/'repeat_buyers.csv').as_posix()}' (HEADER)
    """)

    con.execute("""
        CREATE TEMP TABLE cohort_t AS
        SELECT warehouse_source,country,category,subcategory,currency,
               count(DISTINCT tender_id) tender_count,
               count(DISTINCT buyer_key) FILTER (WHERE buyer_key<>'') unique_buyers,
               median(lean_fit) FILTER (WHERE lean_fit IS NOT NULL) median_lean_fit,
               quantile_cont(lean_fit,.25) FILTER (WHERE lean_fit IS NOT NULL) p25_lean_fit,
               quantile_cont(lean_fit,.75) FILTER (WHERE lean_fit IS NOT NULL) p75_lean_fit,
               median(estimated_value) FILTER (WHERE estimated_value>1) median_estimated_value,
               quantile_cont(estimated_value,.25) FILTER (WHERE estimated_value>1) p25_estimated_value,
               quantile_cont(estimated_value,.75) FILTER (WHERE estimated_value>1) p75_estimated_value,
               avg(CASE WHEN estimated_value>1 THEN 1.0 ELSE 0.0 END)*100 estimate_coverage_pct,
               min(publication_date) first_publication_date,
               max(publication_date) last_publication_date
        FROM tend
        GROUP BY 1,2,3,4,5
    """)
    con.execute("""
        CREATE TEMP TABLE cohort_a AS
        SELECT t.warehouse_source,t.country,t.category,t.subcategory,
               CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,
               count(DISTINCT a.award_id) award_count,
               median(a.award_value) FILTER (WHERE a.award_value>1) median_award_value,
               quantile_cont(a.award_value,.10) FILTER (WHERE a.award_value>1) p10_award_value,
               quantile_cont(a.award_value,.25) FILTER (WHERE a.award_value>1) p25_award_value,
               quantile_cont(a.award_value,.75) FILTER (WHERE a.award_value>1) p75_award_value,
               quantile_cont(a.award_value,.90) FILTER (WHERE a.award_value>1) p90_award_value,
               avg(CASE WHEN a.award_value>1 THEN 1.0 ELSE 0.0 END)*100 award_value_coverage_pct,
               median(a.bidder_count) FILTER (WHERE a.bidder_count IS NOT NULL AND a.bidder_count>=0) median_bidder_count,
               quantile_cont(a.bidder_count,.25) FILTER (WHERE a.bidder_count IS NOT NULL AND a.bidder_count>=0) bidder_p25,
               quantile_cont(a.bidder_count,.75) FILTER (WHERE a.bidder_count IS NOT NULL AND a.bidder_count>=0) bidder_p75,
               avg(CASE WHEN a.bidder_count IS NOT NULL AND a.bidder_count>=0 THEN 1.0 ELSE 0.0 END)*100 bidder_coverage_pct,
               avg(CASE WHEN a.bidder_count=1 THEN 1.0 WHEN a.bidder_count IS NOT NULL THEN 0.0 ELSE NULL END)*100 single_bid_pct,
               avg(CASE WHEN a.bidder_count<=3 THEN 1.0 WHEN a.bidder_count IS NOT NULL THEN 0.0 ELSE NULL END)*100 le3_bidder_pct
        FROM tend t
        JOIN aw a USING(warehouse_source,tender_id)
        GROUP BY 1,2,3,4,5
    """)
    con.execute("""
        CREATE TEMP TABLE repeat_agg AS
        SELECT warehouse_source,country,category,subcategory,currency,
               count(*) FILTER (WHERE tender_count>=3) repeat_buyer_count,
               count(*) FILTER (WHERE tender_count>=5) strong_repeat_buyer_count,
               sum(tender_count) FILTER (WHERE tender_count>=3) repeat_buyer_tenders
        FROM buyer_niche
        GROUP BY 1,2,3,4,5
    """)

    con.execute("""
        CREATE TEMP TABLE br_frac AS
        SELECT warehouse_source,award_id,supplier_id,supplier_name,award_value_allocated,
               1.0/count(*) OVER(PARTITION BY warehouse_source,award_id) fractional_win
        FROM br
    """)
    con.execute("""
        CREATE TEMP TABLE supplier_niche AS
        SELECT t.warehouse_source,t.country,t.category,t.subcategory,
               CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,
               b.supplier_id,any_value(b.supplier_name) supplier_name,
               sum(b.fractional_win) fractional_wins,
               count(DISTINCT a.award_id) linked_award_groups,
               median(b.award_value_allocated) FILTER (WHERE b.award_value_allocated>1) median_explicit_allocated_value
        FROM tend t
        JOIN aw a USING(warehouse_source,tender_id)
        JOIN br_frac b USING(warehouse_source,award_id)
        GROUP BY 1,2,3,4,5,6
    """)
    con.execute("""
        CREATE TEMP TABLE supplier_shares AS
        SELECT *,
               fractional_wins / nullif(sum(fractional_wins) OVER(
                    PARTITION BY warehouse_source,country,category,subcategory,currency
               ),0) supplier_share
        FROM supplier_niche
    """)
    con.execute("""
        CREATE TEMP TABLE fragmentation AS
        SELECT warehouse_source,country,category,subcategory,currency,
               count(*) supplier_count,
               max(supplier_share)*100 top_supplier_share_pct,
               sum(supplier_share*supplier_share)*10000 supplier_hhi,
               CASE WHEN sum(supplier_share*supplier_share)*10000 < 1500 THEN 'FRAGMENTED'
                    WHEN sum(supplier_share*supplier_share)*10000 < 2500 THEN 'MODERATE'
                    ELSE 'CONCENTRATED' END supplier_concentration
        FROM supplier_shares
        GROUP BY 1,2,3,4,5
    """)
    con.execute(f"""
        COPY (
          SELECT *,'NOTICE_FIRST_DERIVED' evidence_type
          FROM fragmentation
          ORDER BY supplier_hhi ASC,supplier_count DESC
        ) TO '{(out/'supplier_fragmentation.csv').as_posix()}' (HEADER)
    """)

    con.execute(f"""
        COPY (
          WITH ranked AS (
            SELECT *,
                   row_number() OVER(
                     PARTITION BY warehouse_source,country,category,subcategory,currency
                     ORDER BY fractional_wins DESC, linked_award_groups DESC, supplier_id
                   ) supplier_rank,
                   supplier_share*100 supplier_share_pct
            FROM supplier_shares
          )
          SELECT warehouse_source,country,category,subcategory,currency,
                 supplier_rank,supplier_id,supplier_name,
                 round(fractional_wins,4) fractional_wins,
                 linked_award_groups,
                 round(supplier_share_pct,4) supplier_share_pct,
                 median_explicit_allocated_value,
                 'NOTICE_FIRST_DERIVED_FRACTIONALIZED' evidence_type
          FROM ranked
          WHERE supplier_rank<=5
          ORDER BY warehouse_source,country,category,subcategory,currency,supplier_rank
        ) TO '{(out/'winner_archetypes.csv').as_posix()}' (HEADER)
    """)

    if h_pub:
        con.execute("""
            CREATE TEMP TABLE monthly AS
            SELECT warehouse_source,country,category,subcategory,currency,
                   month(publication_date) publication_month,
                   count(DISTINCT tender_id) tender_count
            FROM tend
            WHERE publication_date IS NOT NULL
            GROUP BY 1,2,3,4,5,6
        """)
        con.execute(f"""
            COPY (
              WITH totals AS (
                SELECT *,sum(tender_count) OVER(
                  PARTITION BY warehouse_source,country,category,subcategory,currency
                ) total_dated_tenders
                FROM monthly
              ), ranked AS (
                SELECT *,
                       row_number() OVER(
                         PARTITION BY warehouse_source,country,category,subcategory,currency
                         ORDER BY tender_count DESC,publication_month
                       ) rn
                FROM totals
              )
              SELECT warehouse_source,country,category,subcategory,currency,
                     publication_month AS peak_month,
                     tender_count AS peak_month_tenders,
                     total_dated_tenders,
                     round(100.0*tender_count/nullif(total_dated_tenders,0),2) peak_month_share_pct,
                     'NOTICE_FIRST_DERIVED' evidence_type
              FROM ranked WHERE rn=1
              ORDER BY peak_month_share_pct DESC,total_dated_tenders DESC
            ) TO '{(out/'seasonality.csv').as_posix()}' (HEADER)
        """)
    else:
        (out/'seasonality.csv').write_text(
            'warehouse_source,country,category,subcategory,currency,peak_month,peak_month_tenders,total_dated_tenders,peak_month_share_pct,evidence_type\n',
            encoding='utf-8',
        )

    con.execute("""
        CREATE TEMP TABLE cohort AS
        SELECT t.*,
               coalesce(a.award_count,0) award_count,
               a.median_award_value,a.p10_award_value,a.p25_award_value,a.p75_award_value,a.p90_award_value,
               a.award_value_coverage_pct,
               a.median_bidder_count,a.bidder_p25,a.bidder_p75,a.bidder_coverage_pct,a.single_bid_pct,a.le3_bidder_pct,
               coalesce(r.repeat_buyer_count,0) repeat_buyer_count,
               coalesce(r.strong_repeat_buyer_count,0) strong_repeat_buyer_count,
               coalesce(r.repeat_buyer_tenders,0) repeat_buyer_tenders,
               f.supplier_count,f.top_supplier_share_pct,f.supplier_hhi,f.supplier_concentration
        FROM cohort_t t
        LEFT JOIN cohort_a a USING(warehouse_source,country,category,subcategory,currency)
        LEFT JOIN repeat_agg r USING(warehouse_source,country,category,subcategory,currency)
        LEFT JOIN fragmentation f USING(warehouse_source,country,category,subcategory,currency)
    """)
    con.execute(f"""
        COPY (
          SELECT *,'NOTICE_FIRST_DERIVED' evidence_type
          FROM cohort
          ORDER BY tender_count DESC
        ) TO '{(out/'cohort_facts.csv').as_posix()}' (HEADER)
    """)

    con.execute(f"""
        COPY (
          SELECT warehouse_source,country,category,subcategory,currency,
                 award_count,award_value_coverage_pct,
                 p10_award_value,p25_award_value,median_award_value,p75_award_value,p90_award_value,
                 median_estimated_value,p25_estimated_value,p75_estimated_value,estimate_coverage_pct,
                 'NO_FX_MIXING' currency_guardrail,
                 'NOTICE_FIRST_DERIVED' evidence_type
          FROM cohort
          WHERE award_count>0 OR estimate_coverage_pct>0
          ORDER BY award_count DESC,tender_count DESC
        ) TO '{(out/'price_bands.csv').as_posix()}' (HEADER)
    """)

    con.execute("""
        CREATE TEMP TABLE scored AS
        WITH base AS (
          SELECT *,
                 percent_rank() OVER(ORDER BY tender_count) volume_pct,
                 percent_rank() OVER(ORDER BY unique_buyers) buyer_breadth_pct,
                 percent_rank() OVER(ORDER BY coalesce(median_lean_fit,0)) lean_pct,
                 percent_rank() OVER(ORDER BY -coalesce(supplier_hhi,10000)) fragmentation_pct,
                 percent_rank() OVER(ORDER BY coalesce(repeat_buyer_count,0)) repeat_buyer_pct,
                 percent_rank() OVER(ORDER BY coalesce(award_value_coverage_pct,0)+coalesce(estimate_coverage_pct,0)) evidence_pct
          FROM cohort
          WHERE tender_count>=5
        )
        SELECT *,
          CASE
            WHEN bidder_coverage_pct>=30 AND median_bidder_count IS NOT NULL
              THEN greatest(0.0,least(1.0,(8.0-median_bidder_count)/7.0))
            ELSE 0.50
          END competition_score,
          CASE WHEN bidder_coverage_pct>=30 THEN 'COMPETITION_OBSERVED'
               ELSE 'COMPETITION_LOW_COVERAGE_NEUTRAL' END competition_evidence_status,
          round(100*(
              0.12*volume_pct +
              0.18*buyer_breadth_pct +
              0.24*lean_pct +
              0.16*fragmentation_pct +
              0.12*repeat_buyer_pct +
              0.13*CASE
                    WHEN bidder_coverage_pct>=30 AND median_bidder_count IS NOT NULL
                      THEN greatest(0.0,least(1.0,(8.0-median_bidder_count)/7.0))
                    ELSE 0.50
                  END +
              0.05*evidence_pct
          ),2) spm_opportunity_score
        FROM base
    """)
    con.execute(f"""
        COPY (
          SELECT *,
                 CASE
                   WHEN spm_opportunity_score>=80 THEN 'TIER_A'
                   WHEN spm_opportunity_score>=70 THEN 'TIER_B'
                   WHEN spm_opportunity_score>=60 THEN 'TIER_C'
                   ELSE 'TIER_D'
                 END opportunity_tier,
                 'DERIVED_HEURISTIC_PRE_DCE' derived_status
          FROM scored
          ORDER BY spm_opportunity_score DESC,tender_count DESC
        ) TO '{(out/'micro_niche_rank.csv').as_posix()}' (HEADER)
    """)

    con.execute(f"""
        COPY (
          SELECT *,
                 round(
                   spm_opportunity_score
                   + CASE WHEN median_lean_fit>=8 THEN 5 ELSE 0 END
                   + CASE WHEN supplier_hhi<1500 THEN 4 ELSE 0 END
                   + CASE WHEN repeat_buyer_count>=3 THEN 4 ELSE 0 END
                   + CASE WHEN bidder_coverage_pct>=30 AND median_bidder_count<=3 THEN 5 ELSE 0 END
                   + CASE WHEN single_bid_pct>=25 AND bidder_coverage_pct>=30 THEN 3 ELSE 0 END
                 ,2) weird_money_score,
                 'EXPLORATORY_ONLY_REQUIRES_SCOPE_AND_GATE_QA' weird_money_status
          FROM scored
          WHERE coalesce(median_lean_fit,0)>=6
            AND unique_buyers>=3
            AND (supplier_hhi IS NULL OR supplier_hhi<3500)
          ORDER BY weird_money_score DESC,tender_count DESC
        ) TO '{(out/'weird_money_rank.csv').as_posix()}' (HEADER)
    """)

    if h_cpv:
        con.execute(f"""
            COPY (
              WITH x AS (
                SELECT warehouse_source,country,cpv4,category,subcategory,currency,
                       count(DISTINCT tender_id) tender_count,
                       count(DISTINCT buyer_key) FILTER(WHERE buyer_key<>'') unique_buyers,
                       median(lean_fit) FILTER(WHERE lean_fit IS NOT NULL) median_lean_fit,
                       median(estimated_value) FILTER(WHERE estimated_value>1) median_estimated_value
                FROM tend
                WHERE length(cpv4)=4
                GROUP BY 1,2,3,4,5,6
              )
              SELECT *,
                     round(100*(
                       .35*percent_rank() OVER(ORDER BY tender_count) +
                       .35*percent_rank() OVER(ORDER BY unique_buyers) +
                       .30*percent_rank() OVER(ORDER BY coalesce(median_lean_fit,0))
                     ),2) cpv_micro_niche_score,
                     'DERIVED_NO_COMPETITION_COMPONENT' derived_status
              FROM x WHERE tender_count>=5
              ORDER BY cpv_micro_niche_score DESC,tender_count DESC
            ) TO '{(out/'cpv4_micro_niche_rank.csv').as_posix()}' (HEADER)
        """)
    else:
        (out/'cpv4_micro_niche_rank.csv').write_text(
            'warehouse_source,country,cpv4,category,subcategory,currency,tender_count,unique_buyers,median_lean_fit,median_estimated_value,cpv_micro_niche_score,derived_status\n',
            encoding='utf-8',
        )

    con.execute(f"""
        COPY (
          WITH supplier_names AS (
            SELECT warehouse_source,award_id,
                   string_agg(DISTINCT nullif(supplier_name,''), ' | ') supplier_names
            FROM br
            GROUP BY 1,2
          ), x AS (
            SELECT t.warehouse_source,t.country,t.category,t.subcategory,
                   CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END currency,
                   t.tender_id,t.title,t.buyer_name,t.publication_date,t.official_url,
                   t.lean_fit,a.award_id,a.award_value,a.bidder_count,s.supplier_names,
                   row_number() OVER(
                     PARTITION BY t.warehouse_source,t.country,t.category,t.subcategory,
                                  CASE WHEN a.award_currency<>'UNKNOWN' THEN a.award_currency ELSE t.currency END
                     ORDER BY
                       CASE WHEN a.bidder_count IS NULL THEN 999 ELSE a.bidder_count END ASC,
                       coalesce(t.lean_fit,0) DESC,
                       coalesce(a.award_value,0) DESC,
                       t.tender_id
                   ) rn
            FROM tend t
            JOIN aw a USING(warehouse_source,tender_id)
            LEFT JOIN supplier_names s USING(warehouse_source,award_id)
            WHERE a.award_value>1 OR a.bidder_count IS NOT NULL
          )
          SELECT * EXCLUDE(rn),
                 'REPRESENTATIVE_HISTORICAL_EXAMPLE_NOT_BID_VERDICT' evidence_type
          FROM x
          WHERE rn<=3
          ORDER BY warehouse_source,country,category,subcategory,currency
        ) TO '{(out/'historical_examples.csv').as_posix()}' (HEADER)
    """)

    cur = con.execute("""
        SELECT warehouse_source,country,category,subcategory,currency,
               tender_count,unique_buyers,median_lean_fit,
               median_award_value,median_bidder_count,bidder_coverage_pct,
               single_bid_pct,repeat_buyer_count,supplier_count,
               top_supplier_share_pct,supplier_hhi,spm_opportunity_score,
               round(
                   spm_opportunity_score
                   + CASE WHEN median_lean_fit>=8 THEN 5 ELSE 0 END
                   + CASE WHEN supplier_hhi<1500 THEN 4 ELSE 0 END
                   + CASE WHEN repeat_buyer_count>=3 THEN 4 ELSE 0 END
                   + CASE WHEN bidder_coverage_pct>=30 AND median_bidder_count<=3 THEN 5 ELSE 0 END
                   + CASE WHEN single_bid_pct>=25 AND bidder_coverage_pct>=30 THEN 3 ELSE 0 END
                 ,2) weird_money_score
        FROM scored
        WHERE coalesce(median_lean_fit,0)>=6
          AND unique_buyers>=3
          AND (supplier_hhi IS NULL OR supplier_hhi<3500)
        ORDER BY weird_money_score DESC,tender_count DESC
        LIMIT 100
    """)
    top_weird = cur.fetchall()
    top_cols = [d[0] for d in cur.description]
    top_json = [dict(zip(top_cols,row)) for row in top_weird]

    output_rows = {}
    for p in sorted(out.glob('*.csv')):
        output_rows[p.name] = con.execute(
            'SELECT count(*) FROM read_csv_auto(?, header=true, union_by_name=true)',
            [str(p)]
        ).fetchone()[0]

    generated = datetime.now(timezone.utc).isoformat()
    summary = {
        'version': VERSION,
        'status': 'PASS',
        'generated_at': generated,
        'source_release': SOURCE_RELEASE,
        'canonical_counts': counts,
        'source_columns': {
            'historical': {
                'source': h_source, 'tender_id': h_tid, 'country': h_country,
                'buyer_id': h_buyer_id, 'buyer_name': h_buyer_name,
                'category': h_category, 'subcategory': h_subcategory,
                'currency': h_currency, 'lean_fit': h_lean,
                'estimated_value': h_est, 'publication_date': h_pub,
                'title': h_title, 'cpv': h_cpv, 'url': h_url,
            },
            'awards': {
                'source': a_source, 'tender_id': a_tid, 'award_id': a_award_id,
                'award_value': a_value, 'currency': a_currency,
                'bidder_count': a_bidder, 'supplier_id': a_supplier_id,
            },
            'award_suppliers': {
                'source': b_source, 'award_id': b_award_id,
                'supplier_id': b_supplier_id, 'supplier_name': b_supplier_name,
                'allocated_value': b_alloc,
            },
        },
        'outputs': output_rows,
        'guardrails': [
            'No FX mixing: every monetary cohort is currency-isolated.',
            'Award value remains at award/group grain and is never multiplied across consortium suppliers.',
            'Supplier market shares use fractionalized award-group wins.',
            'Bidder competition is neutral in scoring when coverage is below 30%.',
            'All scores are historical derived heuristics and cannot satisfy DCE/eligibility gates.',
            'USA award-first reconstructed procurement is not mixed into this notice-first Global Core v4 analysis.',
        ],
        'top_100_weird_money': top_json,
    }
    (out/'market_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8'
    )

    manifest = {'version': VERSION, 'generated_at': generated, 'files': {}}
    for p in sorted(out.iterdir()):
        if p.is_file():
            blob = p.read_bytes()
            manifest['files'][p.name] = {
                'bytes': len(blob),
                'sha256': hashlib.sha256(blob).hexdigest(),
            }
    (out/'run_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    print(json.dumps({
        'status': 'PASS',
        'version': VERSION,
        'canonical_counts': counts,
        'outputs': output_rows,
        'top_weird_money_preview': top_json[:10],
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
