#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json
from pathlib import Path
import duckdb


def write(path,header,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)


def q(s:str)->str:
    return "'"+s.replace("'","''")+"'"


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--bridge',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute("SET threads=4");con.execute("SET memory_limit='5GB'")
    h=f"read_parquet('{a.historical}')";aw=f"read_parquet('{a.awards}')";br=f"read_parquet('{a.bridge}')"

    # Classification is deliberately TITLE-LED. Scope/description is retained for examples only.
    families=[
      ('OFFICE_STATIONERY',r'(?i)(office supplies|office stationery|stationery supplies|fournitures? de bureau|papeterie|kantoorbenodigdheden|büromaterial|buromaterial)'),
      ('PAPER_ENVELOPES',r'(?i)(copy paper|printing paper|office paper|reprographic paper|papier reprograph|papier pour (impression|photocopie)|briefumschläg|briefumschlag|envelopes?|kuverts?)'),
      ('TONER_INK',r'(?i)(toner|ink cartridges?|printer cartridges?|cartouches? (d.?encre|toner)|tonerkartusch|druckerpatron)'),
      ('OFFICE_FURNITURE',r'(?i)(office furniture|büromöbel|buromobel|mobilier de bureau|kantoormeubilair)'),
      ('SCHOOL_FURNITURE',r'(?i)(school furniture|classroom furniture|mobilier scolaire|schulmöbel|schoolmeubilair)'),
      ('WORKWEAR_PPE_SUPPLY',r'(?i)(supply.*(workwear|ppe|protective clothing|safety footwear)|fourniture.*(vêtements de travail|vetements de travail|epi|équipements de protection individuelle|equipements de protection individuelle)|lieferung.*(arbeitskleidung|schutzkleidung)|levering.*(werkkleding|persoonlijke beschermingsmiddelen))'),
      ('WORKWEAR_MANAGED_RENTAL',r'(?i)(rental.*workwear|hire.*workwear|location.*vêtements de travail|location.*vetements de travail|entretien.*vêtements de travail|laundry.*workwear|miet.*arbeitskleidung)'),
      ('UNIFORMS',r'(?i)(supply.*uniforms?|fourniture.*uniformes?|lieferung.*dienstkleidung|levering.*uniform)'),
      ('PROMOTIONAL_MERCH',r'(?i)(promotional merchandise|promotional products|promotional items|objets publicitaires|goodies|werbeartikel)'),
      ('SIGNAGE_SUPPLY_INSTALL',r'(?i)((supply|fourniture|fabrication|manufacture|lieferung|levering).*(signage|signs|signalétique|signaletique|beschilderung|wegweisung)|(signage|signalétique|signaletique).*(supply|fourniture|fabrication|installation|pose|lieferung))'),
      ('PACKAGING_MATERIALS',r'(?i)((supply|fourniture|lieferung|levering).*(packaging materials|packing materials|cardboard boxes|cartons|emballages)|(packaging materials|packing materials).*(supply|framework))'),
      ('IT_PERIPHERALS',r'(?i)((supply|fourniture|lieferung|levering).*(computer peripherals|monitors|docking stations|keyboards|computer mice|headsets|webcams|périphériques informatiques|peripheriques informatiques)|(computer peripherals|it peripherals).*(framework|supply))'),
      ('MOBILE_DEVICES',r'(?i)((supply|fourniture|lieferung|levering).*(smartphones?|mobile phones?|tablets?|tablet computers)|(smartphones?|mobile phones?|tablets?).*(framework|supply))'),
      ('AV_EQUIPMENT',r'(?i)((supply|fourniture|lieferung|levering).*(projectors?|videoconferencing|video conferencing|audiovisual equipment|audio visual equipment|équipement audiovisuel|equipement audiovisuel)|(audiovisual equipment|audio visual equipment).*(framework|supply))'),
      ('SCHOOL_ART_SUPPLIES',r'(?i)(school supplies|educational supplies|art supplies|craft supplies|fournitures scolaires|matériel pédagogique|materiel pedagogique|schoolbenodigdheden)'),
      ('WASTE_BAGS_SACKS',r'(?i)((supply|fourniture|lieferung|levering).*(waste bags|refuse sacks|garbage bags|bin liners|sacs poubelle|sacs? déchets|sacs? dechets|müllbeutel))'),
      ('FLAGS_BANNERS',r'(?i)((supply|fourniture|fabrication|lieferung|levering).*(flags|banners|drapeaux|banderoles|vlaggen|fahnen))'),
    ]
    case='CASE '+' '.join(f"WHEN regexp_matches(title_l,{q(p)}) THEN {q(f)}" for f,p in families)+" ELSE NULL END"

    con.execute(f"""
      CREATE TABLE hh AS
      SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,
             Buyer_Name buyer,Title title,Scope_Summary scope_summary,Procedure procedure_text,
             try_cast(Official_Estimated_Value as double) estimated_value,lower(coalesce(Title,'')) title_l
      FROM {h}
    """)
    con.execute(f"CREATE TABLE c0 AS SELECT *,{case} goods_family FROM hh")
    # Title negatives remove known semantic collisions rather than relying on scope-wide matches.
    con.execute("""
      CREATE TABLE scoped AS
      SELECT * FROM c0
      WHERE goods_family IS NOT NULL
        AND NOT regexp_matches(title_l,'(?i)(waste collection|waste treatment|recycling of packaging|construction works|road works|civil works|medical imaging|mammography|cardiology|prosthetic|fuel supply)')
    """)
    con.execute(f"CREATE TABLE astat AS SELECT Historical_Tender_ID tender_id,median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>=0) award_value,median(try_cast(Bidder_Count as double)) FILTER(WHERE try_cast(Bidder_Count as double)>=0) bidder_count FROM {aw} GROUP BY 1")
    con.execute(f"""
      CREATE TABLE ts AS
      WITH b0 AS (SELECT Award_ID award_id,coalesce(nullif(Supplier_ID,''),nullif(Supplier_Name,''),'UNKNOWN_SUPPLIER') sid,coalesce(nullif(Supplier_Name,''),nullif(Supplier_ID,''),'UNKNOWN_SUPPLIER') sname FROM {br}),
      bn AS (SELECT *,count(*) over(partition by award_id) n FROM b0), aa AS (SELECT Award_ID award_id,Historical_Tender_ID tender_id FROM {aw})
      SELECT aa.tender_id,bn.sid,bn.sname,1.0/nullif(bn.n,0) w FROM aa JOIN bn USING(award_id)
    """)
    con.execute("CREATE TABLE p AS SELECT s.*,coalesce(a.award_value,s.estimated_value) reference_value,a.bidder_count FROM scoped s LEFT JOIN astat a USING(tender_id)")
    con.execute("CREATE TABLE bs0 AS SELECT goods_family,country,currency,buyer,count(*) n FROM p WHERE buyer<>'' GROUP BY 1,2,3,4")
    con.execute("CREATE TABLE ss0 AS SELECT p.goods_family,p.country,p.currency,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4")
    matrix=con.execute("""
      WITH b AS (
        SELECT goods_family,country,currency,count(*) records,count(distinct nullif(buyer,'')) buyers,
               quantile_cont(reference_value,.25) FILTER(WHERE reference_value>=0) p25_value,
               median(reference_value) FILTER(WHERE reference_value>=0) median_value,
               quantile_cont(reference_value,.75) FILTER(WHERE reference_value>=0) p75_value,
               median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders
        FROM p GROUP BY 1,2,3
      ), rb AS (SELECT goods_family,country,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM bs0 GROUP BY 1,2,3),
      ss AS (SELECT goods_family,country,currency,count(*) suppliers,sum(n) linked_weight,max(n)/nullif(sum(n),0) top_supplier_share FROM ss0 GROUP BY 1,2,3)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.suppliers,ss.linked_weight,ss.top_supplier_share
      FROM b LEFT JOIN rb USING(goods_family,country,currency) LEFT JOIN ss USING(goods_family,country,currency)
      ORDER BY records DESC,buyers DESC
    """).fetchall()
    write(out/'market_matrix.csv',['goods_family','country','currency','records','buyers','p25_value','median_value','p75_value','median_bidders','repeat_buyers','suppliers','linked_weight','top_supplier_share'],matrix)
    winners=con.execute("""
      SELECT goods_family,country,currency,supplier,n,n/nullif(sum(n) over(partition by goods_family,country,currency),0) supplier_share FROM ss0
      QUALIFY row_number() over(partition by goods_family,country,currency order by n desc,supplier)<=10
      ORDER BY goods_family,country,currency,n DESC
    """).fetchall();write(out/'top_winners.csv',['goods_family','country','currency','supplier','weighted_awards','supplier_share'],winners)
    examples=con.execute("""
      SELECT goods_family,country,currency,tender_id,buyer,title,reference_value,bidder_count,procedure_text FROM p
      QUALIFY row_number() over(partition by goods_family,country,currency order by reference_value desc nulls last,tender_id)<=8
      ORDER BY goods_family,country,currency,reference_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['goods_family','country','currency','tender_id','buyer','title','reference_value','median_bidder_count','procedure'],examples)
    summary={'version':'HISTORICAL_STANDARD_GOODS_PRECISION_V2','archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'matched_records':con.execute('select count(*) from p').fetchone()[0],'market_buckets':len(matrix),'families':dict(con.execute('select goods_family,count(*) from p group by 1 order by 2 desc').fetchall()),'classifier':'TITLE_LED_WITH_NEGATIVES','historical_only':True,'live_used':False,'dce_used':False,'currency_mixing':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Historical Standard Goods Precision v2','',f"- Global Core records scanned: **{summary['archive_records_scanned']:,}**",f"- title-led matches after negatives: **{summary['matched_records']:,}**",f"- family-country-currency buckets: **{summary['market_buckets']:,}**",'', 'Historical-only. Unlike v1, classification is title-led to suppress scope contamination. No cohort becomes SPM-ready without representative-title QA.','']
    for r in matrix[:220]:
        fam,country,currency,n,buy,p25,med,p75,bid,rb,sup,lw,share=r
        lines += [f'## {fam} — {country} / {currency}',f'- records **{n}** · buyers **{buy}** · repeat buyers **{rb}** · median **{med if med is not None else "UNKNOWN"}** · p25/p75 **{p25 if p25 is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}**',f'- median bidders **{bid if bid is not None else "UNKNOWN"}** · linked suppliers **{sup if sup is not None else "UNKNOWN"}** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':main()
