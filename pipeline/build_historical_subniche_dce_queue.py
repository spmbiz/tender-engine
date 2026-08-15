#!/usr/bin/env python3
from __future__ import annotations

"""Build a bounded historical DCE research queue from audited sub-niche examples.

Input is representative_examples_subniche.csv from Hunt Sub-Niches v2 Precision.
Output candidates are directly consumable by the public DCE worker contract.
Historical candidates can never receive a final live verdict.
"""
import argparse,csv,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path

TARGETS = [
 'DE · Website maintenance / support',
 'DE · Website relaunch / development',
 'FR · General graphic design',
 'FR · Publication layout / DTP',
 'FR · Written translation',
 'FR · Meeting / debate transcription',
 'FR · Website maintenance / hosting / support',
 'FR · Website redesign / development',
 'FR · General commercial print production',
 'FR · Communication collateral printing',
 'FR · Mailing / routing / fulfilment',
 'FR · Municipal/public magazine printing',
 'FR · Brochure / publication / book printing',
 'FR · Promotional objects / branded goods',
 'QC · General commercial print production',
 'QC · Permits / forms / stationery printing',
 'CA · Written translation',
]


def portal(source:str,url:str)->str:
    s=(source or '').strip().casefold(); u=(url or '').casefold()
    if 'marches-publics.gouv.fr' in u: return 'FR_PLACE'
    if s=='france': return 'FR_BOAMP'
    if s=='germany': return 'DE_DOE'
    if s=='quebec': return 'QC_SEAO'
    if s=='canada federal': return 'CA_CANADABUYS'
    if s=='ireland': return 'GENERIC_PUBLIC_PAGE'
    if s=='united kingdom': return 'GENERIC_PUBLIC_PAGE'
    return 'GENERIC_PUBLIC_PAGE'


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--examples',required=True); ap.add_argument('--out',required=True); ap.add_argument('--per-subniche',type=int,default=3); a=ap.parse_args()
    rows=list(csv.DictReader(open(a.examples,encoding='utf-8')))
    groups=defaultdict(list)
    for r in rows:
        if r.get('sub_niche') not in TARGETS: continue
        if r.get('route') not in ('OPEN_PUBLIC','COMPETITIVE_OTHER'): continue
        url=(r.get('url') or '').strip()
        if not url.startswith(('http://','https://')): continue
        groups[r['sub_niche']].append(r)
    selected=[]
    for niche in TARGETS:
        pool=groups.get(niche,[])
        # Deterministic diversity: buyer then title, preventing a repeated buyer
        # from consuming the full sample where alternatives exist.
        pool=sorted(pool,key=lambda r:((r.get('buyer') or '').casefold(),(r.get('title') or '').casefold(),r.get('url') or ''))
        seen_buyers=set(); first=[]; rest=[]
        for r in pool:
            b=(r.get('buyer') or '').strip().casefold()
            if b and b not in seen_buyers:
                first.append(r); seen_buyers.add(b)
            else: rest.append(r)
        chosen=(first+rest)[:a.per_subniche]
        for r in chosen:
            raw='|'.join([r['sub_niche'],r.get('warehouse_source',''),r.get('title',''),r.get('url','')])
            cid='hist-sub:'+hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]
            url=r['url'].strip(); p=portal(r.get('warehouse_source',''),url)
            selected.append({
              'candidate_id':cid,'historical':True,'historical_sub_niche':r['sub_niche'],
              'source':r.get('warehouse_source',''),'portal':p,'country':r.get('country',''),
              'buyer':r.get('buyer',''),'title':r.get('title',''),'currency':r.get('currency',''),
              'estimated_value':r.get('estimated_value',''),'publication_date':r.get('publication_date',''),
              'primary_source_url':url,'notice_url':url,'route':{'detail_url':url},
              'research_status':'HISTORICAL_DCE_ACCESS_PENDING','final_verdict_allowed':False,
            })
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8') as f:
        for r in selected: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    summary={'contract':'HISTORICAL_SUBNICHE_DCE_QUEUE_V1','selected':len(selected),'per_subniche':a.per_subniche,
             'subniches':dict(Counter(r['historical_sub_niche'] for r in selected)),
             'portals':dict(Counter(r['portal'] for r in selected)),'final_verdict_allowed':False}
    Path(str(out)+'.summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
