#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import duckdb


def write(path,header,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--historical',required=True);ap.add_argument('--awards',required=True);ap.add_argument('--bridge',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute('SET threads=4');con.execute("SET memory_limit='5GB'")
    h=f"read_parquet('{a.historical}')";aw=f"read_parquet('{a.awards}')";br=f"read_parquet('{a.bridge}')"
    con.execute(f"""
      CREATE TABLE hh AS SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,Buyer_Name buyer,Title title,Scope_Summary scope_summary,Procedure procedure_text,coalesce(Main_CPV,'') main_cpv,coalesce(Raw_CPV_Description,'') cpv_description,try_cast(Official_Estimated_Value as double) estimated_value,lower(coalesce(Title,'')) title_l,lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''))) txt FROM {h}
    """)
    con.execute("""
      CREATE TABLE c0 AS SELECT *,CASE
        WHEN regexp_matches(title_l,'(?i)(toner|tonerkart|toner cartridge|ink cartridge|printer cartridge|print consumables|printing consumables|cartouches? d.?encre|cartouches? toner|консуматив.*(принтер|печат)|тонер)') THEN 'TONER_PRINT_CONSUMABLES'
        WHEN regexp_matches(title_l,'(?i)(office supplies|office stationery|stationery supplies|fournitures? de bureau|papeterie|kantoorbenodigdheden|büromaterial|канцеларски материали)') THEN 'OFFICE_STATIONERY'
        WHEN regexp_matches(title_l,'(?i)(copy paper|copier paper|printing paper|reprographic paper|papier reprograph|papier.*photocopie|kopieerpapier|druckerpapier|копирна хартия)') THEN 'COPY_PRINT_PAPER'
        WHEN regexp_matches(title_l,'(?i)(office consumables|consumables for office equipment|printer supplies|copier supplies|office equipment consumables|консумативи за офис техника)') THEN 'OFFICE_EQUIPMENT_CONSUMABLES'
        ELSE NULL END goods_family
      FROM hh
    """)
    con.execute("""
      CREATE TABLE c AS SELECT *,CASE
        WHEN goods_family IS NULL THEN NULL
        WHEN regexp_matches(txt,'(?i)(original toner|original cartridges?|genuine toner|genuine cartridges?|oem toner|oem cartridges?|оригиналн.*тонер|оригиналн.*консуматив)') THEN 'OEM_ORIGINAL_SIGNAL'
        WHEN regexp_matches(txt,'(?i)(compatible toner|compatible cartridges?|remanufactured|remanufactured cartridge|recycled cartridge|equivalent cartridges?|reconditioned|съвместим.*тонер|рециклиран.*тонер)') THEN 'COMPATIBLE_REMAN_SIGNAL'
        ELSE 'BRAND_POLICY_UNSPECIFIED' END brand_policy,
        CASE
          WHEN regexp_matches(txt,'(?i)(framework agreement|framework contract|accord[- ]cadre|marché à bons de commande|marché.*bons de commande|periodic delivery|periodical delivery|annual supply|recurring supply|периодична доставка|rahmenvertrag|raamovereenkomst)') THEN 'RECURRING_FRAMEWORK_SIGNAL'
          ELSE 'RECURRENCE_UNSPECIFIED' END recurrence_signal,
        CASE
          WHEN regexp_matches(txt,'(?i)(installation|installing|integration|maintenance service|repair service|managed print|print management|rental|lease|leasing)') THEN 'SERVICE_OR_INSTALL_COMPONENT'
          ELSE 'PURE_SUPPLY_PLAUSIBLE' END fulfillment_shape
      FROM c0 WHERE goods_family IS NOT NULL
    """)
    con.execute(f"CREATE TABLE astat AS SELECT Historical_Tender_ID tender_id,median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>1) award_value,median(try_cast(Bidder_Count as double)) FILTER(WHERE try_cast(Bidder_Count as double)>=0) bidder_count FROM {aw} GROUP BY 1")
    con.execute(f"""
      CREATE TABLE ts AS WITH b0 AS (SELECT Award_ID award_id,coalesce(nullif(Supplier_ID,''),nullif(Supplier_Name,''),'UNKNOWN_SUPPLIER') sid,coalesce(nullif(Supplier_Name,''),nullif(Supplier_ID,''),'UNKNOWN_SUPPLIER') sname FROM {br}),bn AS (SELECT *,count(*) over(partition by award_id) n FROM b0),aa AS (SELECT Award_ID award_id,Historical_Tender_ID tender_id FROM {aw}) SELECT aa.tender_id,bn.sid,bn.sname,1.0/nullif(bn.n,0) w FROM aa JOIN bn USING(award_id)
    """)
    con.execute("CREATE TABLE p AS SELECT c.*,coalesce(a.award_value,c.estimated_value) reference_value,a.bidder_count FROM c LEFT JOIN astat a USING(tender_id)")
    con.execute("CREATE TABLE bs AS SELECT goods_family,country,currency,brand_policy,fulfillment_shape,buyer,count(*) n FROM p WHERE buyer<>'' GROUP BY 1,2,3,4,5,6")
    con.execute("CREATE TABLE ss AS SELECT p.goods_family,p.country,p.currency,p.brand_policy,p.fulfillment_shape,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4,5,6")
    matrix=con.execute("""
      WITH b AS (SELECT goods_family,country,currency,brand_policy,fulfillment_shape,count(*) records,count(distinct nullif(buyer,'')) buyers,
                        quantile_cont(reference_value,.25) FILTER(WHERE reference_value>1) p25_value,median(reference_value) FILTER(WHERE reference_value>1) median_value,quantile_cont(reference_value,.75) FILTER(WHERE reference_value>1) p75_value,
                        median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders,
                        sum(CASE WHEN recurrence_signal='RECURRING_FRAMEWORK_SIGNAL' THEN 1 ELSE 0 END) recurring_signal_records
                 FROM p GROUP BY 1,2,3,4,5),
      rb AS (SELECT goods_family,country,currency,brand_policy,fulfillment_shape,count(*) FILTER(WHERE n>=2) repeat_buyers FROM bs GROUP BY 1,2,3,4,5),
      sx AS (SELECT goods_family,country,currency,brand_policy,fulfillment_shape,count(*) suppliers,max(n)/nullif(sum(n),0) top_supplier_share FROM ss GROUP BY 1,2,3,4,5)
      SELECT b.*,coalesce(rb.repeat_buyers,0),sx.suppliers,sx.top_supplier_share FROM b LEFT JOIN rb USING(goods_family,country,currency,brand_policy,fulfillment_shape) LEFT JOIN sx USING(goods_family,country,currency,brand_policy,fulfillment_shape)
      ORDER BY goods_family,records DESC
    """).fetchall()
    write(out/'market_matrix.csv',['goods_family','country','currency','brand_policy','fulfillment_shape','records','buyers','p25_value','median_value','p75_value','median_bidders','recurring_signal_records','repeat_buyers','suppliers','top_supplier_share'],matrix)
    # Candidate cohorts: enough observations, pure supply, known currency, fragmented enough, and some competition evidence.
    candidates=con.execute("""
      WITH m AS (
        SELECT goods_family,country,currency,brand_policy,fulfillment_shape,count(*) records,count(distinct nullif(buyer,'')) buyers,median(reference_value) FILTER(WHERE reference_value>1) median_value,median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders FROM p GROUP BY 1,2,3,4,5),
      s0 AS (SELECT goods_family,country,currency,brand_policy,fulfillment_shape,sid,sum(n) n FROM ss GROUP BY 1,2,3,4,5,6),
      sx AS (SELECT goods_family,country,currency,brand_policy,fulfillment_shape,count(*) suppliers,max(n)/nullif(sum(n),0) top_supplier_share FROM s0 GROUP BY 1,2,3,4,5)
      SELECT m.*,sx.suppliers,sx.top_supplier_share,
        round(10*(0.25*least(1,ln(1+m.records)/4)+0.20*least(1,ln(1+m.buyers)/3)+0.20*coalesce(1-sx.top_supplier_share,0)+0.15*least(coalesce(m.median_bidders,0),5)/5+0.20*CASE WHEN m.brand_policy='BRAND_POLICY_UNSPECIFIED' THEN 1 WHEN m.brand_policy='COMPATIBLE_REMAN_SIGNAL' THEN 1 ELSE .45 END),2) broker_routing_score
      FROM m LEFT JOIN sx USING(goods_family,country,currency,brand_policy,fulfillment_shape)
      WHERE m.records>=5 AND m.buyers>=3 AND m.fulfillment_shape='PURE_SUPPLY_PLAUSIBLE' AND m.currency<>'UNKNOWN'
      ORDER BY broker_routing_score DESC,records DESC
    """).fetchall()
    write(out/'candidate_cohorts.csv',['goods_family','country','currency','brand_policy','fulfillment_shape','records','buyers','median_value','median_bidders','suppliers','top_supplier_share','broker_routing_score'],candidates)
    buyers=con.execute("""SELECT goods_family,country,currency,buyer,count(*) records FROM p WHERE buyer<>'' GROUP BY 1,2,3,4 QUALIFY row_number() over(partition by goods_family,country,currency order by count(*) desc,buyer)<=30 ORDER BY goods_family,country,currency,records DESC""").fetchall()
    write(out/'top_buyers.csv',['goods_family','country','currency','buyer','records'],buyers)
    suppliers=con.execute("""SELECT goods_family,country,currency,brand_policy,fulfillment_shape,sid,any_value(supplier) supplier,sum(n) weighted_awards FROM ss GROUP BY 1,2,3,4,5,6 QUALIFY row_number() over(partition by goods_family,country,currency,brand_policy,fulfillment_shape order by sum(n) desc,sid)<=30 ORDER BY goods_family,country,currency,weighted_awards DESC""").fetchall()
    write(out/'top_suppliers.csv',['goods_family','country','currency','brand_policy','fulfillment_shape','supplier_id','supplier','weighted_awards'],suppliers)
    examples=con.execute("""SELECT goods_family,country,currency,brand_policy,recurrence_signal,fulfillment_shape,tender_id,buyer,title,substr(scope_summary,1,1400) scope_excerpt,main_cpv,reference_value,bidder_count,procedure_text FROM p QUALIFY row_number() over(partition by goods_family,country,currency,brand_policy,fulfillment_shape order by reference_value desc nulls last,tender_id)<=20 ORDER BY goods_family,country,currency,reference_value DESC NULLS LAST""").fetchall()
    write(out/'examples.csv',['goods_family','country','currency','brand_policy','recurrence_signal','fulfillment_shape','tender_id','buyer','title','scope_excerpt','main_cpv','reference_value','bidder_count','procedure'],examples)
    summary={'version':'HISTORICAL_OFFICE_CONSUMABLES_BROKER_PRECISION_V1','archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'classified_rows':con.execute('select count(*) from p').fetchone()[0],'families':dict(con.execute('select goods_family,count(*) from p group by 1 order by 2 desc').fetchall()),'brand_policies':dict(con.execute('select brand_policy,count(*) from p group by 1 order by 2 desc').fetchall()),'pure_supply_rows':con.execute("select count(*) from p where fulfillment_shape='PURE_SUPPLY_PLAUSIBLE'").fetchone()[0],'candidate_cohorts':len(candidates),'historical_only':True,'currency_mixing':False,'record_deletion':False,'warning':'Brand policy is inferred only from explicit text. Unspecified does not mean compatible products are allowed. Broker score is model routing, not margin or eligibility.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Office Consumables Broker Precision v1','',f"- Global Core records scanned **{summary['archive_records_scanned']:,}**",f"- strict office/print consumable rows **{summary['classified_rows']:,}**",f"- pure-supply-plausible rows **{summary['pure_supply_rows']:,}**",f"- candidate country/currency cohorts **{summary['candidate_cohorts']}**",'', 'No brand flexibility is assumed unless explicit. Currency remains isolated. Broker score is only a routing heuristic.','']
    for row in candidates[:40]:
        fam,country,currency,brand,shape,n,buy,med,bid,sup,share,score=row
        lines.append(f'- **{fam} · {country} {currency} · {brand}** — records={n} buyers={buy} suppliers={sup} median={med} bidders={bid} top_share={round(100*share,1) if share is not None else "UNKNOWN"}% routing={score}/10')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
