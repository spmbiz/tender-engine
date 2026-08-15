#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from pathlib import Path
import duckdb


def write(path,header,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)


def sql(s): return "'"+s.replace("'","''")+"'"


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--bridge',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute("SET threads=4");con.execute("SET memory_limit='5GB'")
    h=f"read_parquet('{a.historical}')"; aw=f"read_parquet('{a.awards}')"; br=f"read_parquet('{a.bridge}')"
    patterns=[
      ('SOFTWARE_RESELLER',r'(?i)(softwarebroker|software[ -]broker|software reseller|software resell|licen[cs].*reseller|licentiemakelaar|lizenzbroker|licensing solution partner|jälleenmyynti|återförsälj.*(programvara|licens))'),
      ('CONSULTANT_BROKER',r'(?i)(konsultmäklare|konsultförmedl|consultant broker|consultancy broker|consultant marketplace|courtier.*consultant|intermediation.*consultant)'),
      ('RECRUITMENT_STAFFING_AGENCY',r'(?i)(staffing agency|recruitment agency|employment agency|temporary staffing|temporary help services|labou?r hire|uitzend|interim staffing|agence.*intérim|personaldienstleist|personalvermittlung)'),
      ('INSURANCE_BROKER',r'(?i)(insurance broker|insurance brokerage|courtier.*assurance|assurance.*courtier|verzekeringsmakelaar|versicherungsbroker|versicherungsmakler)'),
      ('ENERGY_BROKER',r'(?i)(energy broker|electricity broker|gas broker|courtier.*énergie|courtier.*energie|energiemäklare|energimakelaar|energiebroker)'),
      ('REAL_ESTATE_BROKER',r'(?i)(real estate broker|property broker|estate agent|makelaar.*vastgoed|vastgoedmakelaar|immobilienmakler|courtier.*immobilier)'),
      ('FREIGHT_FORWARDER_LOGISTICS_BROKER',r'(?i)(freight forwarder|freight forwarding|shipping agent|customs broker|douane.*courtier|commissionnaire de transport|speditör|spediteur|expéditeur.*fret)'),
      ('TRAVEL_MANAGEMENT_AGENCY',r'(?i)(travel management compan|travel agency services|business travel agency|agence de voyage|reisagent|reisbureau|travel broker)'),
      ('MEDIA_BUYING_AGENCY',r'(?i)(media buying|media agency|advertising buying|achat d.?espace publicitaire|centrale d.?achat média|centrale d.?achat media)'),
      ('PRINT_MAIL_FULFILMENT',r'(?i)(print broker|printing broker|mailing house|mail fulfil|mail fulfillment|mise sous pli|routage postal|bulk mailing)'),
      ('PROMOTIONAL_MERCH_RESELLER',r'(?i)(promotional merchandise|promotional products|promotional items|goodies|objets publicitaires|merchandise reseller)'),
      ('ICT_HARDWARE_VAR',r'(?i)(value added reseller|\bvar\b.*(ict|it|hardware|software)|ict reseller|hardware reseller|technology reseller)'),
      ('PROCUREMENT_AGENT',r'(?i)(procurement agent|purchasing agent|buying agent|centrale d.?achat.*service|group purchasing organisation|group purchasing organization)'),
      ('GENERIC_BROKER_INTERMEDIARY',r'(?i)(brokerage services|broker services|intermediary services|intermediation services|courtage|courtier|makelaar|mäklare|vermittler)'),
    ]
    case='CASE '+' '.join(f"WHEN regexp_matches(txt,{sql(p)}) THEN {sql(lbl)}" for lbl,p in patterns)+" ELSE NULL END"
    con.execute(f"""
      CREATE TABLE hh AS
      SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,Buyer_Name buyer,Title title,
             Procedure procedure_text,try_cast(Official_Estimated_Value as double) estimated_value,
             lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''),coalesce(Subcategory,''))) txt
      FROM {h}
    """)
    con.execute(f"CREATE TABLE scoped0 AS SELECT *,{case} market_family FROM hh")
    con.execute("CREATE TABLE scoped AS SELECT * FROM scoped0 WHERE market_family IS NOT NULL")
    con.execute(f"""
      CREATE TABLE astat AS
      SELECT Historical_Tender_ID tender_id,median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>=0) award_value
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
    con.execute("CREATE TABLE p AS SELECT s.*,coalesce(a.award_value,s.estimated_value) reference_value FROM scoped s LEFT JOIN astat a USING(tender_id)")
    con.execute("CREATE TABLE bs0 AS SELECT market_family,country,currency,buyer,count(*) n FROM p WHERE buyer<>'' GROUP BY 1,2,3,4")
    con.execute("CREATE TABLE ss0 AS SELECT p.market_family,p.country,p.currency,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4")
    matrix=con.execute("""
      WITH b AS (
        SELECT market_family,country,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,
               quantile_cont(reference_value,.25) FILTER(WHERE reference_value>=0) p25_value,
               median(reference_value) FILTER(WHERE reference_value>=0) median_value,
               quantile_cont(reference_value,.75) FILTER(WHERE reference_value>=0) p75_value
        FROM p GROUP BY 1,2,3
      ), rb AS (SELECT market_family,country,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM bs0 GROUP BY 1,2,3),
      ss AS (SELECT market_family,country,currency,count(*) suppliers,sum(n) linked_weight,max(n)/nullif(sum(n),0) top_supplier_share FROM ss0 GROUP BY 1,2,3)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.suppliers,ss.linked_weight,ss.top_supplier_share
      FROM b LEFT JOIN rb USING(market_family,country,currency) LEFT JOIN ss USING(market_family,country,currency)
      ORDER BY records DESC,buyers DESC
    """).fetchall()
    write(out/'market_matrix.csv',['family','country','currency','records','buyers','p25_value','median_value','p75_value','repeat_buyers','suppliers','linked_weight','top_supplier_share'],matrix)
    winners=con.execute("""
      SELECT market_family,country,currency,sname,n,n/nullif(sum(n) over(partition by market_family,country,currency),0) supplier_share
      FROM ss0 QUALIFY row_number() over(partition by market_family,country,currency order by n desc,sname)<=10
      ORDER BY market_family,country,currency,n DESC
    """).fetchall(); write(out/'top_winners.csv',['family','country','currency','supplier','weighted_awards','supplier_share'],winners)
    buyers=con.execute("""
      SELECT market_family,country,currency,buyer,n FROM bs0
      QUALIFY row_number() over(partition by market_family,country,currency order by n desc,buyer)<=10
      ORDER BY market_family,country,currency,n DESC
    """).fetchall();write(out/'top_buyers.csv',['family','country','currency','buyer','records'],buyers)
    examples=con.execute("""
      SELECT market_family,country,currency,tender_id,buyer,title,reference_value,procedure_text FROM p
      QUALIFY row_number() over(partition by market_family,country,currency order by reference_value desc nulls last,tender_id)<=6
      ORDER BY market_family,country,currency,reference_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['family','country','currency','tender_id','buyer','title','reference_value','procedure'],examples)
    summary={'archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'matched_records':con.execute('select count(*) from p').fetchone()[0],'market_buckets':len(matrix),'families':dict(con.execute('select market_family,count(*) from p group by 1 order by 2 desc').fetchall()),'historical_only':True,'live_used':False,'dce_used':False,'currency_mixing':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Explicit Broker / Intermediary Census v2','',f"- Global Core records scanned: **{summary['archive_records_scanned']:,}**",f"- Explicit/intermediary matches: **{summary['matched_records']:,}**",f"- family-country-currency buckets: **{summary['market_buckets']:,}**",'', 'Historical notice-first evidence only. Regex family assignment is a discovery aid; representative examples and market structure must be semantically QA’d before promotion.','']
    for r in matrix[:180]:
        fam,country,currency,n,buy,p25,med,p75,rb,sup,lw,supplier_share=r
        lines += [f'## {fam} — {country} / {currency}',f'- records **{n}** · buyers **{buy}** · repeat buyers **{rb}** · median **{med if med is not None else "UNKNOWN"}** · p25/p75 **{p25 if p25 is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}**',f'- linked suppliers **{sup if sup is not None else "UNKNOWN"}** · top supplier share **{round(100*supplier_share,1) if supplier_share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__': main()
