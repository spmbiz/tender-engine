#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import duckdb


def write(path,header,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)

def q(s): return "'"+s.replace("'","''")+"'"

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--bridge',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute("SET threads=4");con.execute("SET memory_limit='5GB'")
    h=f"read_parquet('{a.historical}')";aw=f"read_parquet('{a.awards}')";br=f"read_parquet('{a.bridge}')"
    cats=[
      ('OFFICE_STATIONERY',r'(?i)(office supplies|office stationery|stationery supplies|fournitures de bureau|papeterie|kantoorbenodigdheden|büromaterial|buromaterial)'),
      ('PAPER_ENVELOPES',r'(?i)(copy paper|printing paper|office paper|envelopes|papier reprograph|papier d.?impression|papier de bureau|briefumschläge|kuvert)'),
      ('TONER_INK_PRINT_CONSUMABLES',r'(?i)(toner|ink cartridge|printer cartridge|print consumables|cartouche.*encre|cartouche.*toner|druckerpatron|tonerkartusch)'),
      ('FURNITURE_STANDARD',r'(?i)(office furniture|school furniture|classroom furniture|chairs and tables|desks and chairs|mobilier de bureau|mobilier scolaire|kantoormeubilair|büromöbel)'),
      ('PPE_WORKWEAR',r'(?i)(personal protective equipment|\bppe\b|workwear|protective clothing|vêtements de travail|vetements de travail|arbeitskleidung|werkkleding|safety footwear)'),
      ('UNIFORMS',r'(?i)(uniforms|uniform clothing|uniformes|uniformkleding|dienstkleidung)'),
      ('PROMOTIONAL_MERCH',r'(?i)(promotional merchandise|promotional products|promotional items|promotional goods|objets publicitaires|goodies|giveaways|werbeartikel)'),
      ('SIGNAGE_STANDARD',r'(?i)(signage|signs and nameplates|traffic signs|information signs|signalétique|signaletique|schildersystem|bewegwijzering)'),
      ('PACKAGING',r'(?i)(packaging materials|packing materials|cardboard boxes|cartons|emballages|materiaal.*verpakking|verpakkingsmateriaal|verpackungsmaterial)'),
      ('IT_PERIPHERALS',r'(?i)(computer peripherals|keyboards|computer mice|monitors|computer screens|docking stations|webcams|headsets|périphériques informatiques|peripheriques informatiques)'),
      ('MOBILE_DEVICES',r'(?i)(smartphones|mobile phones|tablets|tablet computers|téléphones mobiles|telephones mobiles|mobiele telefoons)'),
      ('AUDIOVISUAL_STANDARD',r'(?i)(projectors|video conferencing equipment|audiovisual equipment|audio visual equipment|équipement audiovisuel|equipement audiovisuel)'),
      ('SCHOOL_ART_SUPPLIES',r'(?i)(school supplies|educational supplies|art supplies|craft supplies|fournitures scolaires|matériel pédagogique|materiel pedagogique|schoolbenodigdheden)'),
      ('KITCHEN_CATERING_SUPPLIES',r'(?i)(kitchen supplies|catering supplies|tableware|disposable tableware|kitchen utensils|ustensiles de cuisine|vaisselle jetable)'),
      ('CLEANING_HYGIENE_SUPPLIES',r'(?i)(cleaning supplies|cleaning consumables|janitorial supplies|hygiene supplies|produits d.?entretien|produits.*hygiène|reinigungsmittel)'),
      ('BAGS_WASTE_SACKS',r'(?i)(waste bags|refuse sacks|garbage bags|bin liners|sacs poubelle|sac.*déchet|müllbeutel)'),
      ('FLAGS_BANNERS',r'(?i)(flags and banners|flags|banners|drapeaux|banderoles|vlaggen|fahnen)'),
    ]
    case='CASE '+' '.join(f"WHEN regexp_matches(txt,{q(p)}) THEN {q(c)}" for c,p in cats)+" ELSE NULL END"
    con.execute(f"""
    CREATE TABLE hh AS
    SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,Buyer_Name buyer,Title title,
           Procedure procedure_text,try_cast(Official_Estimated_Value as double) estimated_value,
           lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''),coalesce(Subcategory,''))) txt
    FROM {h}
    """)
    con.execute(f"CREATE TABLE s0 AS SELECT *,{case} goods_family FROM hh")
    # Keep heavy/install contamination explicit so semantic QA can down-rank it; do not delete raw hits.
    con.execute("""
      CREATE TABLE scoped AS SELECT *,
        regexp_matches(txt,'(?i)(construction|civil works|installation works|building works|architect|engineering services|maintenance of roads)') heavy_install_flag
      FROM s0 WHERE goods_family IS NOT NULL
    """)
    con.execute(f"CREATE TABLE astat AS SELECT Historical_Tender_ID tender_id,median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>=0) award_value FROM {aw} GROUP BY 1")
    con.execute(f"""
      CREATE TABLE ts AS
      WITH b0 AS (SELECT Award_ID award_id,coalesce(nullif(Supplier_ID,''),nullif(Supplier_Name,''),'UNKNOWN_SUPPLIER') sid,coalesce(nullif(Supplier_Name,''),nullif(Supplier_ID,''),'UNKNOWN_SUPPLIER') sname FROM {br}),
      bn AS (SELECT *,count(*) over(partition by award_id) n FROM b0),aa AS (SELECT Award_ID award_id,Historical_Tender_ID tender_id FROM {aw})
      SELECT aa.tender_id,bn.sid,bn.sname,1.0/nullif(bn.n,0) w FROM aa JOIN bn USING(award_id)
    """)
    con.execute("CREATE TABLE p AS SELECT s.*,coalesce(a.award_value,s.estimated_value) reference_value FROM scoped s LEFT JOIN astat a USING(tender_id)")
    con.execute("CREATE TABLE bs0 AS SELECT goods_family,country,currency,buyer,count(*) n FROM p WHERE buyer<>'' GROUP BY 1,2,3,4")
    con.execute("CREATE TABLE ss0 AS SELECT p.goods_family,p.country,p.currency,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4")
    matrix=con.execute("""
      WITH b AS (
       SELECT goods_family,country,currency,count(*) records,count(*) FILTER(WHERE heavy_install_flag) heavy_flagged,
              count(distinct nullif(buyer,'')) buyers,
              quantile_cont(reference_value,.25) FILTER(WHERE reference_value>=0) p25_value,
              median(reference_value) FILTER(WHERE reference_value>=0) median_value,
              quantile_cont(reference_value,.75) FILTER(WHERE reference_value>=0) p75_value
       FROM p GROUP BY 1,2,3),
      rb AS (SELECT goods_family,country,currency,count(*) FILTER(WHERE n>=2) repeat_buyers FROM bs0 GROUP BY 1,2,3),
      ss AS (SELECT goods_family,country,currency,count(*) suppliers,sum(n) linked_weight,max(n)/nullif(sum(n),0) top_supplier_share FROM ss0 GROUP BY 1,2,3)
      SELECT b.*,coalesce(rb.repeat_buyers,0),ss.suppliers,ss.linked_weight,ss.top_supplier_share
      FROM b LEFT JOIN rb USING(goods_family,country,currency) LEFT JOIN ss USING(goods_family,country,currency)
      ORDER BY records DESC,buyers DESC
    """).fetchall()
    write(out/'market_matrix.csv',['goods_family','country','currency','records','heavy_flagged','buyers','p25_value','median_value','p75_value','repeat_buyers','suppliers','linked_weight','top_supplier_share'],matrix)
    winners=con.execute("""
      SELECT goods_family,country,currency,supplier,n,n/nullif(sum(n) over(partition by goods_family,country,currency),0) supplier_share FROM ss0
      QUALIFY row_number() over(partition by goods_family,country,currency order by n desc,supplier)<=10
      ORDER BY goods_family,country,currency,n DESC
    """).fetchall();write(out/'top_winners.csv',['goods_family','country','currency','supplier','weighted_awards','supplier_share'],winners)
    buyers=con.execute("""
      SELECT goods_family,country,currency,buyer,n FROM bs0
      QUALIFY row_number() over(partition by goods_family,country,currency order by n desc,buyer)<=10
      ORDER BY goods_family,country,currency,n DESC
    """).fetchall();write(out/'top_buyers.csv',['goods_family','country','currency','buyer','records'],buyers)
    examples=con.execute("""
      SELECT goods_family,country,currency,tender_id,buyer,title,reference_value,procedure_text,heavy_install_flag FROM p
      QUALIFY row_number() over(partition by goods_family,country,currency order by heavy_install_flag asc,reference_value desc nulls last,tender_id)<=8
      ORDER BY goods_family,country,currency,heavy_install_flag,reference_value DESC NULLS LAST
    """).fetchall();write(out/'examples.csv',['goods_family','country','currency','tender_id','buyer','title','reference_value','procedure','heavy_install_flag'],examples)
    summary={'archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'matched_records':con.execute('select count(*) from p').fetchone()[0],'market_buckets':len(matrix),'families':dict(con.execute('select goods_family,count(*) from p group by 1 order by 2 desc').fetchall()),'historical_only':True,'live_used':False,'dce_used':False,'currency_mixing':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Historical Standard Goods Census v1','',f"- Global Core notice-first records scanned: **{summary['archive_records_scanned']:,}**",f"- standardized-goods text matches: **{summary['matched_records']:,}**",f"- family-country-currency buckets: **{summary['market_buckets']:,}**",'', 'Historical-only discovery layer. Heavy/install contamination is flagged, not silently deleted. Representative examples must be semantically QA’d before atlas promotion.','']
    for r in matrix[:220]:
        fam,country,currency,n,heavy,buy,p25,med,p75,rb,sup,lw,share=r
        lines += [f'## {fam} — {country} / {currency}',f'- records **{n}** · heavy/install flagged **{heavy}** · buyers **{buy}** · repeat buyers **{rb}**',f'- median **{med if med is not None else "UNKNOWN"}** · p25/p75 **{p25 if p25 is not None else "UNKNOWN"} / {p75 if p75 is not None else "UNKNOWN"}** · linked suppliers **{sup if sup is not None else "UNKNOWN"}** · top supplier share **{round(100*share,1) if share is not None else "UNKNOWN"}%**','']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':main()
