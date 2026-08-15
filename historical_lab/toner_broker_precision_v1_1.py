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
      CREATE TABLE hh AS SELECT Historical_Tender_ID tender_id,Country country,upper(coalesce(nullif(Currency,''),'UNKNOWN')) currency,Buyer_Name buyer,Title title,Scope_Summary scope_summary,Procedure procedure_text,coalesce(Main_CPV,'') main_cpv,try_cast(Official_Estimated_Value as double) estimated_value,lower(coalesce(Title,'')) title_l,lower(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''))) txt FROM {h}
    """)
    con.execute("""
      CREATE TABLE c AS SELECT *,CASE
        WHEN regexp_matches(txt,'(?i)(\boriginal toner\b|\boriginal cartridges?\b|\bgenuine toner\b|\bgenuine cartridges?\b|\boem toner\b|\boem cartridges?\b|оригиналн.*тонер|оригиналн.*консуматив)') THEN 'OEM_ORIGINAL_SIGNAL'
        WHEN regexp_matches(txt,'(?i)(\bcompatible toner\b|\bcompatible cartridges?\b|\bremanufactured\b|\brecycled cartridges?\b|\bequivalent cartridges?\b|\breconditioned\b|съвместим.*тонер|рециклиран.*тонер)') THEN 'COMPATIBLE_REMAN_SIGNAL'
        ELSE 'BRAND_POLICY_UNSPECIFIED' END brand_policy,
        CASE WHEN regexp_matches(txt,'(?i)(framework agreement|framework contract|accord[- ]cadre|rahmenvertrag|raamovereenkomst|periodic delivery|annual supply|периодична доставка)') THEN 'RECURRING_FRAMEWORK_SIGNAL' ELSE 'RECURRENCE_UNSPECIFIED' END recurrence_signal,
        CASE WHEN regexp_matches(txt,'(?i)(managed print|print management|maintenance service|repair service|rental|lease|leasing|installation|integration)') THEN 'SERVICE_OR_INSTALL_COMPONENT' ELSE 'PURE_SUPPLY_PLAUSIBLE' END fulfillment_shape
      FROM hh
      WHERE regexp_matches(title_l,'(?i)(\btoner\b|\btonerkartusche[n]?\b|\btonerkartuschen\b|\btoner cartridge[s]?\b|\bink cartridge[s]?\b|\bprinter cartridge[s]?\b|\bprint consumables\b|\bprinting consumables\b|cartouches? d.?encre|cartouches? toner|консуматив.*(принтер|печат)|\bтонер\b)')
        AND NOT regexp_matches(title_l,'(?i)(beton|concrete|betonerhalt|betonsanier|betoninstand)')
    """)
    con.execute(f"CREATE TABLE astat AS SELECT Historical_Tender_ID tender_id,median(try_cast(Award_Value as double)) FILTER(WHERE try_cast(Award_Value as double)>1) award_value,median(try_cast(Bidder_Count as double)) FILTER(WHERE try_cast(Bidder_Count as double)>=0) bidder_count FROM {aw} GROUP BY 1")
    con.execute(f"""CREATE TABLE ts AS WITH b0 AS (SELECT Award_ID award_id,coalesce(nullif(Supplier_ID,''),nullif(Supplier_Name,''),'UNKNOWN_SUPPLIER') sid,coalesce(nullif(Supplier_Name,''),nullif(Supplier_ID,''),'UNKNOWN_SUPPLIER') sname FROM {br}),bn AS (SELECT *,count(*) over(partition by award_id) n FROM b0),aa AS (SELECT Award_ID award_id,Historical_Tender_ID tender_id FROM {aw}) SELECT aa.tender_id,bn.sid,bn.sname,1.0/nullif(bn.n,0) w FROM aa JOIN bn USING(award_id)""")
    con.execute("CREATE TABLE p AS SELECT c.*,coalesce(a.award_value,c.estimated_value) reference_value,a.bidder_count FROM c LEFT JOIN astat a USING(tender_id)")
    con.execute("CREATE TABLE ss AS SELECT p.country,p.currency,p.brand_policy,p.fulfillment_shape,t.sid,any_value(t.sname) supplier,sum(t.w) n FROM p JOIN ts t USING(tender_id) WHERE t.sid<>'UNKNOWN_SUPPLIER' GROUP BY 1,2,3,4,5")
    matrix=con.execute("""
      WITH b AS (SELECT country,currency,brand_policy,fulfillment_shape,count(*) records,count(distinct nullif(buyer,'')) buyers,quantile_cont(reference_value,.25) FILTER(WHERE reference_value>1) p25_value,median(reference_value) FILTER(WHERE reference_value>1) median_value,quantile_cont(reference_value,.75) FILTER(WHERE reference_value>1) p75_value,median(bidder_count) FILTER(WHERE bidder_count>=0) median_bidders,sum(CASE WHEN recurrence_signal='RECURRING_FRAMEWORK_SIGNAL' THEN 1 ELSE 0 END) recurring_signal_records FROM p GROUP BY 1,2,3,4),
      s0 AS (SELECT country,currency,brand_policy,fulfillment_shape,sid,sum(n) n FROM ss GROUP BY 1,2,3,4,5),sx AS (SELECT country,currency,brand_policy,fulfillment_shape,count(*) suppliers,max(n)/nullif(sum(n),0) top_supplier_share FROM s0 GROUP BY 1,2,3,4)
      SELECT b.*,sx.suppliers,sx.top_supplier_share FROM b LEFT JOIN sx USING(country,currency,brand_policy,fulfillment_shape) ORDER BY records DESC
    """).fetchall()
    write(out/'market_matrix.csv',['country','currency','brand_policy','fulfillment_shape','records','buyers','p25_value','median_value','p75_value','median_bidders','recurring_signal_records','suppliers','top_supplier_share'],matrix)
    candidates=[r for r in matrix if r[4]>=5 and r[5]>=3 and r[3]=='PURE_SUPPLY_PLAUSIBLE' and r[1]!='UNKNOWN']
    write(out/'candidate_cohorts.csv',['country','currency','brand_policy','fulfillment_shape','records','buyers','p25_value','median_value','p75_value','median_bidders','recurring_signal_records','suppliers','top_supplier_share'],candidates)
    examples=con.execute("""SELECT country,currency,brand_policy,fulfillment_shape,tender_id,buyer,title,substr(scope_summary,1,1400) scope_excerpt,main_cpv,reference_value,bidder_count,recurrence_signal FROM p QUALIFY row_number() over(partition by country,currency,brand_policy,fulfillment_shape order by reference_value desc nulls last,tender_id)<=25 ORDER BY country,currency,reference_value DESC NULLS LAST""").fetchall()
    write(out/'examples.csv',['country','currency','brand_policy','fulfillment_shape','tender_id','buyer','title','scope_excerpt','main_cpv','reference_value','bidder_count','recurrence_signal'],examples)
    summary={'version':'HISTORICAL_TONER_BROKER_PRECISION_V1_1','archive_records_scanned':con.execute('select count(*) from hh').fetchone()[0],'strict_toner_rows':con.execute('select count(*) from p').fetchone()[0],'pure_supply_rows':con.execute("select count(*) from p where fulfillment_shape='PURE_SUPPLY_PLAUSIBLE'").fetchone()[0],'candidate_cohorts':len(candidates),'brand_policies':dict(con.execute('select brand_policy,count(*) from p group by 1 order by 2 desc').fetchall()),'historical_only':True,'currency_mixing':False,'record_deletion':False,'supersession':'The TONER_PRINT_CONSUMABLES portion of office-consumables v1 is superseded because QA found German Betonerhaltungsarbeiten substring collisions. Office stationery/paper families from v1 are not superseded by this toner-only correction.','warning':'Unspecified brand policy does not imply compatible/remanufactured supplies are acceptable.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Toner Broker Precision v1.1','',f"- Global Core rows scanned **{summary['archive_records_scanned']:,}**",f"- strict toner/ink/print-consumable rows **{summary['strict_toner_rows']:,}**",f"- pure-supply rows **{summary['pure_supply_rows']:,}**",'', 'This correction uses lexical boundaries and explicit concrete/Beton exclusions. The old Germany toner aggregate is superseded.','']
    for r in candidates[:40]:
        country,currency,brand,shape,n,buy,p25,med,p75,bid,rec,sup,share=r
        lines.append(f'- **{country} {currency} · {brand}** — records={n} buyers={buy} suppliers={sup} p25/median/p75={p25}/{med}/{p75} bidders={bid} top_share={round(100*share,1) if share is not None else "UNKNOWN"}%')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
