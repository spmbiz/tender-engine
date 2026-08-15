from __future__ import annotations

import csv, io, json, os, zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/IT_ANAC_DELTA'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
API='https://dati.anticorruzione.it/opendata/api/3/action/package_search'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.6 (+public procurement research)','Accept':'application/json,*/*'})
def clean(v):return ' '.join(str(v or '').split())
def main():
    r=S.get(API,params={'q':'CIG aggiornamenti delta','rows':20},timeout=90);r.raise_for_status();data=r.json();results=((data.get('result') or {}).get('results') or [])
    pkg=next((x for x in results if 'aggiornamenti delta' in clean(x.get('title')).lower() and clean(x.get('title')).lower().startswith('cig')),results[0] if results else None)
    if not pkg:
        stats={'source':'IT_ANAC_DELTA','raw_materialized':0,'current_materialized':0,'errors':[{'type':'DATASET_NOT_FOUND'}],'generated_at':NOW.isoformat(),'official_url':API};(OUT/'stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8');print(json.dumps(stats,indent=2));raise SystemExit(2)
    resources=[]
    for x in pkg.get('resources') or []:
        resources.append({'id':x.get('id'),'name':x.get('name'),'format':x.get('format'),'url':x.get('url'),'last_modified':x.get('last_modified'),'size':x.get('size')})
    (OUT/'resource_inventory.json').write_text(json.dumps({'package_id':pkg.get('id'),'title':pkg.get('title'),'metadata_modified':pkg.get('metadata_modified'),'resources':resources},indent=2,ensure_ascii=False),encoding='utf-8')
    csvres=next((x for x in reversed(pkg.get('resources') or []) if clean(x.get('format')).upper()=='CSV' and x.get('url')),None)
    rows=[];download={}
    if csvres:
        rr=S.get(csvres['url'],timeout=180);download={'url':csvres['url'],'status':rr.status_code,'bytes':len(rr.content),'content_type':rr.headers.get('content-type')}
        if rr.ok and len(rr.content)<=300_000_000:
            body=rr.content
            texts=[]
            if body[:2]==b'PK':
                try:
                    z=zipfile.ZipFile(io.BytesIO(body))
                    for n in z.namelist():
                        if n.lower().endswith('.csv'):texts.append(z.read(n).decode('utf-8-sig',errors='replace'))
                except Exception as exc:download['zip_error']=repr(exc)
            else:texts=[body.decode('utf-8-sig',errors='replace')]
            for text in texts:
                sample=text[:10000];delim=';' if sample.count(';')>sample.count(',') else ','
                for row in csv.DictReader(io.StringIO(text),delimiter=delim):
                    if row:rows.append(row)
    with (OUT/'delta_rows.jsonl').open('w',encoding='utf-8') as f:
        for x in rows:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    # CIG delta is lifecycle/open-contract intelligence, not an open-bid feed. Do not promote it into current candidates.
    (OUT/'current.jsonl').write_text('',encoding='utf-8')
    stats={'source':'IT_ANAC_DELTA','raw_materialized':len(rows),'current_materialized':0,'lane':'ARCHIVE_LIFECYCLE_DELTA','generated_at':NOW.isoformat(),'errors':[],'official_url':API,'package_id':pkg.get('id'),'package_title':pkg.get('title'),'metadata_modified':pkg.get('metadata_modified'),'resource_count':len(resources),'download':download}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not resources:raise SystemExit(2)
if __name__=='__main__':main()
