#!/usr/bin/env python3
from __future__ import annotations

"""Semantic promotion gate for candidate lanes surfaced by Exhaustive Every-Record v1.

Purpose
-------
The exhaustive reader intentionally maximises recall. This script is the stricter
commercial gate between that discovery layer and live-harvester historical priors.
It re-reads Global Core v4 notice-first facts and evaluates only expansion lanes
that were not part of the original high-precision digital thesis.

Rules
-----
* No lane is promoted because of volume alone.
* Source grain and currencies are preserved; no FX mixing.
* OPEN_PUBLIC is separated from direct/framework/unknown routes.
* Physical / operational / licensed / complex collisions are explicitly blocked.
* CORE_DIGITAL and BROKER_RESELL are distinct commercial motions.
* Historical output never satisfies live eligibility/DCE gates.
"""

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

VERSION = "SPM_SEMANTIC_PROMOTION_V2"


def qi(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def choose(cols: set[str], *names: str) -> str | None:
    cmap = {c.casefold(): c for c in cols}
    for n in names:
        if n.casefold() in cmap:
            return cmap[n.casefold()]
    return None


def txt(c: str | None, default: str = "''") -> str:
    return f"trim(cast({qi(c)} as varchar))" if c else default


def write_csv(path: Path, headers: list[str], rows: list[tuple]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--historical", required=True)
    p.add_argument("--awards", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(out / "qa.duckdb"))
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=4")
    con.execute("SET memory_limit='5GB'")

    hc = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [a.historical]).fetchall()}
    ac = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [a.awards]).fetchall()}

    hs = choose(hc, "Warehouse_Source")
    hid = choose(hc, "Historical_Tender_ID")
    country = choose(hc, "Country")
    buyer = choose(hc, "Buyer_Name")
    buyer_id = choose(hc, "Buyer_ID")
    currency = choose(hc, "Currency")
    title = choose(hc, "Title")
    scope = choose(hc, "Scope_Summary")
    cpv = choose(hc, "CPV_NAICS_or_Local_Code")
    cpvd = choose(hc, "Raw_CPV_Description")
    rawcat = choose(hc, "Raw_Spend_Category")
    proc = choose(hc, "Procedure", "Procedure_Type", "Competition_Type")
    est = choose(hc, "Official_Estimated_Value")
    url = choose(hc, "Primary_Source_URL")

    aas = choose(ac, "Warehouse_Source")
    aat = choose(ac, "Historical_Tender_ID")
    av = choose(ac, "Award_Value")
    acur = choose(ac, "Currency")
    abid = choose(ac, "Bidder_Count")

    required = {"historical.source": hs, "historical.id": hid, "historical.title": title,
                "award.source": aas, "award.tender": aat}
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SystemExit(json.dumps({"missing": missing, "historical_cols": sorted(hc), "award_cols": sorted(ac)}, indent=2))

    source = txt(hs)
    tid = txt(hid)
    ctry = f"upper(coalesce(nullif({txt(country)},''),{source}))"
    cur = f"upper(coalesce(nullif({txt(currency)},''),'UNKNOWN'))"
    bname = txt(buyer)
    bid = txt(buyer_id)
    bkey = f"lower(regexp_replace(coalesce(nullif({bid},''),{bname}),'\\s+',' ','g'))"
    ttitle = txt(title)
    tscope = txt(scope)
    tcpv = txt(cpv)
    tcpvd = txt(cpvd)
    traw = txt(rawcat)
    tproc = txt(proc, "'UNKNOWN'")
    test = f"try_cast({qi(est)} as double)" if est else "NULL::DOUBLE"
    turl = txt(url)
    text = f"lower(concat_ws(' ',{ttitle},{tscope},{tcpv},{tcpvd},{traw}))"

    asrc = txt(aas)
    atid = txt(aat)
    aval = f"try_cast({qi(av)} as double)" if av else "NULL::DOUBLE"
    awardcur = f"upper(coalesce(nullif({txt(acur)},''),'UNKNOWN'))" if acur else "'UNKNOWN'"
    bidder = f"try_cast({qi(abid)} as double)" if abid else "NULL::DOUBLE"

    # Broad candidate trigger: intentionally recall-oriented, mirroring the discovery layer.
    loose = f"""
    CASE
      WHEN regexp_matches({text}, '(software licen[cs]|software subscription|saas|cloud subscription|licence logiciel|licences logicielles|subscription software)') THEN 'Software licences / SaaS resale'
      WHEN regexp_matches({text}, '(audio visual|audiovisual equipment|av equipment|computer hardware|laptop|desktop computer|monitor|display screen|projector|network equipment|server hardware)') THEN 'Hardware / AV resale'
      WHEN regexp_matches({text}, '(office supplies|stationery|papeterie|fournitures de bureau|toner|ink cartridge)') THEN 'Office supplies / consumables resale'
      WHEN regexp_matches({text}, '(uniforms?|workwear|protective clothing|personal protective equipment|\\bppe\\b|vêtements de travail|vetements de travail)') THEN 'Uniforms / PPE resale'
      WHEN regexp_matches({text}, '(courier|messenger service|parcel delivery|mail delivery|postal services|distribution de courrier|livraison de colis)') THEN 'Courier / mail fulfilment'
      WHEN regexp_matches({text}, '(e[- ]learning|online training|training delivery|formation en ligne|formation à distance|formation a distance|learning management system|\\blms\\b)') THEN 'Training / e-learning'
      WHEN regexp_matches({text}, '(temporary staff|temporary staffing|agency staff|interim staff|recruitment services|intérim|interim|personnel temporaire)') THEN 'Recruitment / temporary staffing'
      WHEN regexp_matches({text}, '(event management|event production|conference management|organisation d.événement|organisation d.evenement|gestion d.événement|gestion d.evenement)') THEN 'Event support / production'
      WHEN regexp_matches({text}, '(promotional merchandise|promotional items|objets publicitaires|articles promotionnels|goodies|branded merchandise)') THEN 'Promotional merchandise'
      WHEN regexp_matches({text}, '(signage|signalétique|signaletique|wayfinding|enseigne|display boards)') THEN 'Signage / display production'
      ELSE NULL
    END
    """

    # Hard collision vocabulary. These are not automatically bad procurements; they
    # are bad evidence for a lean/broker lane unless the title explicitly isolates a
    # simple supply/digital deliverable.
    physical_complex = f"regexp_matches({text}, '(construction|civil works|building works|renovation|rénovation|installation works|electrical works|mechanical works|medical|clinical|laboratory|scientific instrument|weapon|ammunition|military vehicle|security screening|x[- ]ray|fire alarm|engineering services|architectural|facility management|fleet maintenance|vehicle maintenance)')"
    labour_heavy = f"regexp_matches({text}, '(on[- ]site staffing|onsite staffing|temporary labour|temporary labor|agency workers|manpower|personnel placement|recruitment agency|executive search|payroll services)')"
    onsite_event = f"regexp_matches({text}, '(venue|catering|stage construction|stand build|booth build|security staff|hostess|event logistics|event venue|physical event|onsite event|on-site event)')"
    install_heavy = f"regexp_matches({text}, '(installation and maintenance|supply and install|supply, installation|delivery and installation|installation of signage|sign manufacture and installation|fit[- ]out|cabling|wiring)')"

    strict = f"""
    CASE
      WHEN regexp_matches({text}, '(software licen[cs](e|ing|es)?|licen[cs]e renewal|software subscription|subscription renewal|saas subscription|cloud software subscription|licence logiciel|licences logicielles)')
           AND NOT regexp_matches({text}, '(custom software development|application development|software development services|system integration|implementation services|migration services|consulting services|cybersecurity services|penetration test|managed service|maintenance and development)')
        THEN 'Software licences / SaaS resale'

      WHEN regexp_matches({text}, '(supply|purchase|procurement|delivery|framework).{0,80}(laptop|desktop computer|computer monitor|display screen|projector|audio visual equipment|audiovisual equipment|av equipment|network switch|server hardware|computer hardware)')
           AND NOT {physical_complex}
           AND NOT {install_heavy}
        THEN 'Hardware / AV resale'

      WHEN regexp_matches({text}, '(office supplies|stationery|papeterie|fournitures de bureau|toner cartridge|ink cartridge|printer consumables)')
           AND NOT regexp_matches({text}, '(office furniture|fit[- ]out|printer fleet|managed print service|copier rental|photocopier rental)')
        THEN 'Office supplies / consumables resale'

      WHEN regexp_matches({text}, '(supply|purchase|procurement|framework).{0,80}(uniforms?|workwear|protective clothing|personal protective equipment|\\bppe\\b|vêtements de travail|vetements de travail)')
           AND NOT regexp_matches({text}, '(body armour|body armor|ballistic|firefighter breathing|respiratory apparatus|hazmat suit|chemical protective|military uniform system)')
        THEN 'Uniforms / PPE resale'

      WHEN regexp_matches({text}, '(e[- ]learning content|digital learning content|online learning modules?|online training modules?|e[- ]learning modules?|learning management system|\\blms\\b|virtual learning content|interactive learning content)')
           AND NOT regexp_matches({text}, '(classroom training|in[- ]person training|face[- ]to[- ]face training|onsite training|on-site training|coaching services|trainer services|training venue)')
        THEN 'Training / e-learning'

      WHEN regexp_matches({text}, '(promotional merchandise|promotional items|objets publicitaires|articles promotionnels|branded merchandise|corporate gifts)')
           AND NOT regexp_matches({text}, '(event management|campaign management|warehousing service|full service marketing)')
        THEN 'Promotional merchandise'

      WHEN regexp_matches({text}, '(supply|manufacture|production|printing).{0,80}(signage|signalétique|signaletique|wayfinding signs|display boards)')
           AND NOT {install_heavy}
           AND NOT regexp_matches({text}, '(traffic signal|railway signal|electrical signal|fire alarm|security system)')
        THEN 'Signage / display production'

      WHEN regexp_matches({text}, '(courier services|parcel delivery services|mail fulfilment|mail fulfillment|postal fulfilment|postal fulfillment|mailing fulfilment|mailing fulfillment)')
           AND NOT regexp_matches({text}, '(freight forwarding|heavy haul|vehicle fleet|medical courier|dangerous goods)')
        THEN 'Courier / mail fulfilment'

      WHEN regexp_matches({text}, '(event production|conference production|virtual event production|hybrid event production)')
           AND NOT {onsite_event}
        THEN 'Event support / production'

      WHEN regexp_matches({text}, '(temporary staffing|agency staff|temporary staff|recruitment services|intérim|interim staff)')
           AND NOT {labour_heavy}
        THEN 'Recruitment / temporary staffing'
      ELSE NULL
    END
    """

    pl = f"lower(coalesce({tproc},''))"
    sl = f"lower(coalesce({source},''))"
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
        WHEN {pl} IN ('restricted procedure','restricted','below threshold - limited competition','negotiated procedure with prior call for competition','competitive procedure with negotiation','competitive dialogue') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('below threshold - without competition','direct award','negotiated without publication of a contract notice') THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%framework%' OR {pl} LIKE '%dynamic market%' THEN 'FRAMEWORK_DPS_CALLOFF'
        ELSE 'UNKNOWN' END
      ELSE 'UNKNOWN'
    END
    """

    con.execute(f"""
      CREATE TABLE candidates AS
      SELECT {source} warehouse_source, {tid} tender_id, {ctry} country,
             {bkey} buyer_key, {bname} buyer_name, {cur} currency,
             {ttitle} title, {tscope} scope, {tcpv} cpv_code, {tproc} procedure,
             {test} estimated_value, {turl} official_url,
             {loose} loose_lane, {strict} strict_lane, {route} route_band,
             CASE WHEN {physical_complex} THEN 1 ELSE 0 END physical_complex_collision,
             CASE WHEN {install_heavy} THEN 1 ELSE 0 END install_collision,
             CASE WHEN {onsite_event} THEN 1 ELSE 0 END onsite_event_collision,
             CASE WHEN {labour_heavy} THEN 1 ELSE 0 END labour_collision
      FROM read_parquet(?)
      WHERE ({loose}) IS NOT NULL
    """, [a.historical])

    con.execute(f"""
      CREATE TEMP TABLE award_tender AS
      SELECT {asrc} warehouse_source, {atid} tender_id,
             median(CASE WHEN {aval}>0 THEN {aval} END) median_award_value,
             max(CASE WHEN {aval}>0 THEN {awardcur} END) award_currency,
             median(CASE WHEN {bidder}>=0 THEN {bidder} END) median_bidders,
             count(*) FILTER (WHERE {bidder} IS NOT NULL AND {bidder}>=0) bidder_n,
             count(*) FILTER (WHERE {bidder}=1) one_bid_rows
      FROM read_parquet(?)
      GROUP BY 1,2
    """, [a.awards])

    con.execute("""
      CREATE TABLE q AS
      SELECT c.*, a.median_award_value, a.award_currency, a.median_bidders, a.bidder_n, a.one_bid_rows
      FROM candidates c LEFT JOIN award_tender a USING (warehouse_source,tender_id)
    """)

    headers = ["lane","loose_hits","strict_hits","strict_share_pct","open_public_strict","buyers_strict",
               "median_estimated_value","median_award_value","bidder_evidence_rows","median_bidders",
               "single_bid_pct","physical_complex_collisions","install_collisions","onsite_event_collisions","labour_collisions"]
    rows = con.execute("""
      SELECT loose_lane,
             count(*) loose_hits,
             count(*) FILTER (WHERE strict_lane=loose_lane) strict_hits,
             round(100.0*count(*) FILTER (WHERE strict_lane=loose_lane)/count(*),2) strict_share_pct,
             count(*) FILTER (WHERE strict_lane=loose_lane AND route_band='OPEN_PUBLIC') open_public_strict,
             count(DISTINCT buyer_key) FILTER (WHERE strict_lane=loose_lane) buyers_strict,
             median(estimated_value) FILTER (WHERE strict_lane=loose_lane AND estimated_value>0),
             median(median_award_value) FILTER (WHERE strict_lane=loose_lane AND median_award_value>0),
             sum(coalesce(bidder_n,0)) FILTER (WHERE strict_lane=loose_lane),
             median(median_bidders) FILTER (WHERE strict_lane=loose_lane AND bidder_n>0),
             round(100.0*sum(coalesce(one_bid_rows,0)) FILTER (WHERE strict_lane=loose_lane)/nullif(sum(coalesce(bidder_n,0)) FILTER (WHERE strict_lane=loose_lane),0),2),
             sum(physical_complex_collision),sum(install_collision),sum(onsite_event_collision),sum(labour_collision)
      FROM q GROUP BY 1 ORDER BY strict_hits DESC
    """).fetchall()
    write_csv(out / "lane_qa_summary.csv", headers, rows)

    # Country/route cohorts: no cross-currency aggregation of value statistics.
    cohort_headers = ["lane","source","country","route","currency","records","buyers","median_estimated_value","median_award_value","median_bidders","bidder_rows","single_bid_pct"]
    cohort_rows = con.execute("""
      SELECT strict_lane,warehouse_source,country,route_band,currency,count(*),count(DISTINCT buyer_key),
             median(estimated_value) FILTER (WHERE estimated_value>0),
             median(median_award_value) FILTER (WHERE median_award_value>0 AND (award_currency=currency OR award_currency IS NULL OR award_currency='UNKNOWN')),
             median(median_bidders) FILTER (WHERE bidder_n>0),sum(coalesce(bidder_n,0)),
             round(100.0*sum(coalesce(one_bid_rows,0))/nullif(sum(coalesce(bidder_n,0)),0),2)
      FROM q WHERE strict_lane IS NOT NULL
      GROUP BY 1,2,3,4,5 HAVING count(*)>=3
      ORDER BY records DESC
    """).fetchall()
    write_csv(out / "strict_cohorts.csv", cohort_headers, cohort_rows)

    # Diversity-preserving samples for manual semantic review. Highest-value rows do
    # not dominate: row_number partitions by lane/source/country and stable hash.
    sample_headers = ["lane","source","country","route","currency","title","scope","cpv","estimated_value","median_award_value","median_bidders","url"]
    sample_rows = con.execute("""
      WITH z AS (
        SELECT *, row_number() OVER (
          PARTITION BY strict_lane,warehouse_source,country
          ORDER BY hash(tender_id,title)
        ) rn
        FROM q WHERE strict_lane IS NOT NULL
      )
      SELECT strict_lane,warehouse_source,country,route_band,currency,title,scope,cpv_code,estimated_value,median_award_value,median_bidders,official_url
      FROM z WHERE rn<=8
      ORDER BY strict_lane,warehouse_source,country,rn
      LIMIT 1200
    """).fetchall()
    write_csv(out / "manual_review_samples.csv", sample_headers, sample_rows)

    reject_headers = ["loose_lane","source","country","title","cpv","collision_reason","url"]
    reject_rows = con.execute("""
      WITH z AS (
        SELECT *,
          CASE
            WHEN physical_complex_collision=1 THEN 'PHYSICAL_OR_COMPLEX_COLLISION'
            WHEN install_collision=1 THEN 'INSTALLATION_COLLISION'
            WHEN onsite_event_collision=1 THEN 'ONSITE_EVENT_COLLISION'
            WHEN labour_collision=1 THEN 'LABOUR_OPERATION_COLLISION'
            ELSE 'FAILED_STRICT_SEMANTIC_GATE' END reason,
          row_number() OVER (PARTITION BY loose_lane ORDER BY hash(tender_id,title)) rn
        FROM q WHERE strict_lane IS NULL
      )
      SELECT loose_lane,warehouse_source,country,title,cpv_code,reason,official_url
      FROM z WHERE rn<=80 ORDER BY loose_lane,rn
    """).fetchall()
    write_csv(out / "rejected_false_positive_samples.csv", reject_headers, reject_rows)

    # Commercial posture is a policy prior, not an eligibility verdict.
    posture = {
        "Software licences / SaaS resale": ("PROMOTE_BROKER", "Low-delivery software resale/subscription motion; validate reseller/channel constraints per DCE."),
        "Hardware / AV resale": ("HOLD_BROKER", "Potential broker margin but working-capital, warranty, delivery and installation burden can dominate."),
        "Office supplies / consumables resale": ("HOLD_BROKER", "Easy fulfilment but likely commodity margins/logistics; require margin and payment-term proof."),
        "Uniforms / PPE resale": ("HOLD_BROKER", "Brokerable but sizing, standards, samples and inventory may create execution pain."),
        "Training / e-learning": ("PROMOTE_CORE", "Only strict digital-learning/LMS/content subset; classroom/trainer-heavy work is excluded."),
        "Promotional merchandise": ("PROMOTE_BROKER", "Brokerable physical production lane; DCE must allow subcontracting and acceptable samples/logistics."),
        "Signage / display production": ("HOLD_BROKER", "Pure production can be brokered, but installation/site burden is common and explicitly filtered."),
        "Courier / mail fulfilment": ("REJECT_CORE", "Operational physical network business; useful only as buyer/subcontractor intelligence."),
        "Event support / production": ("HOLD", "Even clean titles frequently conceal onsite/cadence burden; no live bonus until DCE/sample validation."),
        "Recruitment / temporary staffing": ("REJECT_CORE", "Labour/employer/compliance motion is outside lean SPM core."),
    }
    summary_by_lane = {r[0]: r for r in rows}
    decisions=[]
    for lane,(decision,reason) in posture.items():
        r=summary_by_lane.get(lane)
        if not r:
            decisions.append((lane,"HOLD_NO_EVIDENCE",0,0,0,reason+" No strict historical hits."))
            continue
        strict_hits=int(r[2] or 0); share=float(r[3] or 0); open_hits=int(r[4] or 0)
        final=decision
        # Evidence floor: policy cannot promote a lane without enough strict facts.
        if decision.startswith("PROMOTE") and (strict_hits < 25 or open_hits < 5):
            final="HOLD_LOW_EVIDENCE"
        decisions.append((lane,final,strict_hits,open_hits,share,reason))
    write_csv(out / "promotion_decisions.csv", ["lane","decision","strict_hits","open_public_hits","strict_share_pct","reason"], decisions)

    manifest = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_grain": "GLOBAL_CORE_V4_NOTICE_FIRST",
        "safety": {
            "historical_only": True,
            "satisfies_dce_gates": False,
            "affects_final_verdict": False,
            "no_fx_mixing": True,
            "award_first_used": False,
        },
        "counts": {
            "loose_candidates": con.execute("select count(*) from q").fetchone()[0],
            "strict_candidates": con.execute("select count(*) from q where strict_lane is not null").fetchone()[0],
            "strict_open_public": con.execute("select count(*) from q where strict_lane is not null and route_band='OPEN_PUBLIC'").fetchone()[0],
        },
        "decisions": [dict(zip(["lane","decision","strict_hits","open_public_hits","strict_share_pct","reason"], d)) for d in decisions],
    }
    (out / "promotion_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# SPM Semantic Promotion QA v2", "", f"Version: `{VERSION}`", "",
        "This gate re-tests expansion lanes discovered by the exhaustive reader with stricter semantics. It does not replace Market Intelligence v9 for already-QA-clean lanes and does not satisfy any live DCE requirement.", "",
        f"- Loose expansion candidates: **{manifest['counts']['loose_candidates']:,}**",
        f"- Strict semantic candidates: **{manifest['counts']['strict_candidates']:,}**",
        f"- Strict candidates on OPEN_PUBLIC routes: **{manifest['counts']['strict_open_public']:,}**", "",
        "## Promotion decisions", "",
        "|Lane|Decision|Strict hits|Open-public|Strict/loose|Rationale|", "|---|---|---:|---:|---:|---|"
    ]
    for lane,decision,sh,oh,share,reason in decisions:
        lines.append(f"|{lane}|{decision}|{sh:,}|{oh:,}|{share:.2f}%|{reason.replace('|','/')}|")
    lines += ["", "## Interpretation", "",
              "- `PROMOTE_CORE` may contribute a small pre-DCE live discovery bonus after manual sample review.",
              "- `PROMOTE_BROKER` is a separate resale/arbitrage motion; it must not be treated as AI-native fulfilment.",
              "- `HOLD*` remains searchable but contributes no historical priority bonus until further QA/economics validation.",
              "- `REJECT_CORE` may still be commercially useful to a different operator model, but is outside SPM lean-core scoring.",
              "- All mandatory eligibility, references, turnover, insurance, language, onsite and subcontracting rules remain DCE-controlled."]
    (out / "PROMOTION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
