#!/usr/bin/env python3
from __future__ import annotations

"""Global Core v4-aware historical DCE sample selector.

Produces immutable historical candidates directly consumable by the public DCE
resolver contract. Historical candidates can never receive a final live verdict.
"""
import argparse,csv,gzip,hashlib,json,math,re
from collections import Counter,defaultdict
from pathlib import Path
from typing import Iterator

LEAN_TERMS={
 'website':12,'web site':12,'web portal':10,'cms':10,'software':5,'application':4,
 'hosting':7,'maintenance':4,'graphic':10,'design':7,'branding':9,'creative':8,
 'video':10,'audiovisual':9,'animation':9,'marketing':7,'communications':6,
 'social media':8,'content':7,'editorial':8,'publication':5,'print':7,'printing':8,
 'brochure':7,'translation':8,'transcription':10,'data':4,'automation':7,
 'artificial intelligence':8,
}
LEAN_CPV_DIVISIONS={'72','79','48','22','30'}
EXCLUDE_LANES={'USA','USA_FEDERAL','USASPENDING','AU_AUSTENDER_AWARD_FIRST','AUSTRALIA_AWARD_FIRST'}


def _norm(v): return re.sub(r'\s+',' ',str(v or '').strip())

def _first(row,*keys):
    for k in keys:
        if k in row:
            v=_norm(row.get(k))
            if v and v.upper() not in {'UNKNOWN','NULL','NONE','N/A'}: return v
    low={str(k).casefold():k for k in row}
    for k in keys:
        actual=low.get(k.casefold())
        if actual is not None:
            v=_norm(row.get(actual))
            if v and v.upper() not in {'UNKNOWN','NULL','NONE','N/A'}: return v
    return ''

def _open_csv(path):
    if path.suffix.casefold()=='.gz':return gzip.open(path,'rt',encoding='utf-8-sig',errors='replace',newline='')
    return path.open('r',encoding='utf-8-sig',errors='replace',newline='')

def _iter_rows(path:Path,batch_size=10000)->Iterator[dict]:
    if path.suffix.casefold()=='.parquet':
        import duckdb
        con=duckdb.connect(database=':memory:');con.execute('PRAGMA threads=4')
        cur=con.execute('SELECT * FROM read_parquet(?)',[str(path)]);cols=[d[0] for d in cur.description]
        while True:
            batch=cur.fetchmany(batch_size)
            if not batch:break
            for vals in batch:yield dict(zip(cols,vals))
        con.close();return
    with _open_csv(path) as f:yield from csv.DictReader(f)

def _cpv(row):
    raw=_first(row,'CPV_NAICS_or_Local_Code','cpv','cpv_code','main_cpv','classification_id')
    digits=re.sub(r'\D','',raw);return digits[:2] if len(digits)>=2 else ''

def _source(row):return _first(row,'Warehouse_Source','source','lane','source_name','portal')

def _identity(row):
    rid=_first(row,'Historical_Tender_ID','record_id','source_record_id','notice_id','id')
    if rid:return rid
    raw='|'.join([_first(row,'Country','country','country_code'),_first(row,'Buyer_Name','buyer_name','buyer'),_first(row,'Title','title'),_first(row,'Publication_Date','publication_date','date')])
    return 'hist:'+hashlib.sha256(raw.encode('utf-8',errors='replace')).hexdigest()[:24]

def _portal(source,url):
    s=(source or '').strip().casefold();u=(url or '').casefold()
    if 'marches-publics.gouv.fr' in u:return 'FR_PLACE'
    if 'etenders.gov.ie' in u:return 'IRELAND_ETENDERS'
    if s=='france':return 'FR_BOAMP'
    if s=='germany':return 'DE_DOE'
    if s=='quebec':return 'QC_SEAO'
    if s=='canada federal':return 'CA_CANADABUYS'
    if s=='united kingdom':return 'GENERIC_PUBLIC_PAGE'
    if s=='ireland':return 'IRELAND_ETENDERS' if 'etenders.gov.ie' in u else 'GENERIC_PUBLIC_PAGE'
    return 'GENERIC_PUBLIC_PAGE'

def _score(row):
    title=_first(row,'Title','title','tender_title','description').casefold();score=0;reasons=[]
    for term,pts in LEAN_TERMS.items():
        if term in title:score+=pts;reasons.append(f'+{pts}:{term}')
    cpv=_cpv(row)
    if cpv in LEAN_CPV_DIVISIONS:score+=5;reasons.append(f'+5:cpv-{cpv}')
    url=_first(row,'Primary_Source_URL','primary_source_url','source_url','notice_url','url')
    if url.startswith(('http://','https://')):score+=4;reasons.append('+4:source-url')
    if _first(row,'Buyer_Name','buyer_name','buyer','contracting_authority'):score+=2;reasons.append('+2:buyer')
    return score,reasons

def _canonical(row,score,reasons):
    source=_source(row);url=_first(row,'Primary_Source_URL','primary_source_url','source_url','notice_url','url')
    p=_portal(source,url)
    return {
      'candidate_id':_identity(row),'historical':True,'source':source,'portal':p,
      'country':_first(row,'Country','country','country_code','buyer_country').upper(),
      'buyer':_first(row,'Buyer_Name','buyer_name','buyer','contracting_authority'),
      'title':_first(row,'Title','title','tender_title','description'),'cpv_division':_cpv(row),
      'publication_date':_first(row,'Publication_Date','publication_date','date','notice_date'),
      'award_date':_first(row,'Award_Date','award_date'),'primary_source_url':url,'notice_url':url,
      'route':{'detail_url':url},'sample_priority':score,'sample_reason':reasons,
      'research_status':'HISTORICAL_DCE_PENDING','final_verdict_allowed':False,
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);ap.add_argument('--limit',type=int,default=10000);ap.add_argument('--min-score',type=int,default=5);ap.add_argument('--country-cap-share',type=float,default=.20);ap.add_argument('--buyer-cap',type=int,default=20);a=ap.parse_args()
    path=Path(a.input)
    if not path.is_file():raise SystemExit(f'missing input: {path}')
    candidates=[];raw_rows=excluded_award_first=0
    for row in _iter_rows(path):
        raw_rows+=1;source=_source(row).upper();evidence=_first(row,'Evidence_Grain','evidence_grain','evidence_lane','grain').casefold()
        if source in EXCLUDE_LANES or 'award-first' in evidence or 'award_first' in evidence:excluded_award_first+=1;continue
        score,reasons=_score(row)
        if score<a.min_score:continue
        rec=_canonical(row,score,reasons)
        if not rec['primary_source_url']:continue
        candidates.append((score,rec))
    candidates.sort(key=lambda x:(-x[0],x[1]['country'],x[1]['candidate_id']))
    country_cap=max(50,math.ceil(a.limit*a.country_cap_share));cc=Counter();bc=Counter();selected=[];seen=set();buckets=defaultdict(list)
    for _,rec in candidates:buckets[(rec['country'] or 'UNKNOWN',rec['cpv_division'] or 'UNKNOWN')].append(rec)
    active=sorted(buckets,key=lambda k:(-buckets[k][0]['sample_priority'],k))
    while active and len(selected)<a.limit:
        nxt=[]
        for key in active:
            if len(selected)>=a.limit:break
            queue=buckets[key]
            while queue:
                rec=queue.pop(0);cid=rec['candidate_id'];bk=f"{rec['country']}|{rec['buyer'].casefold()}"
                if cid in seen or cc[rec['country']]>=country_cap or (rec['buyer'] and bc[bk]>=a.buyer_cap):continue
                seen.add(cid);cc[rec['country']]+=1
                if rec['buyer']:bc[bk]+=1
                selected.append(rec);break
            if queue and cc[key[0]]<country_cap:nxt.append(key)
        active=nxt
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8') as f:
        for rec in selected:f.write(json.dumps(rec,ensure_ascii=False,separators=(',',':'))+'\n')
    summary={'contract':'HISTORICAL_DCE_SAMPLE_V2','input_format':path.suffix.casefold().lstrip('.'),'raw_rows':raw_rows,'excluded_award_first':excluded_award_first,'eligible_candidates':len(candidates),'selected':len(selected),'country_cap':country_cap,'buyer_cap':a.buyer_cap,'countries':dict(cc),'portals':dict(Counter(r['portal'] for r in selected)),'cpv_divisions':dict(Counter(r['cpv_division'] for r in selected)),'final_verdict_allowed':False,'purpose':'historical DCE/gate prevalence research; not bid recommendations'}
    Path(str(out)+'.summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
