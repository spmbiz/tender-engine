from __future__ import annotations

import gzip, json, os
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/IT_OCP_MIRROR'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
# OCP Data Registry mirrors ANAC OCDS and reports monthly retrieval from the official ANAC source.
URL=os.getenv('IT_OCP_URL','https://fastly.data.open-contracting.org/downloads/italy_anac/4006/full.jsonl.gz')
MAX_BYTES=int(os.getenv('IT_OCP_MAX_BYTES','300000000'))
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.0 (+public procurement research)','Accept':'application/gzip,application/octet-stream,*/*'})
def main():
    r=S.get(URL,timeout=240);r.raise_for_status();body=r.content
    if len(body)>MAX_BYTES:raise RuntimeError(f'archive too large: {len(body)}')
    gz=OUT/'italy_anac_full.jsonl.gz';gz.write_bytes(body)
    n=0;tenders=0;awards=0;sample=[]
    with gzip.open(gz,'rt',encoding='utf-8',errors='replace') as f:
        for line in f:
            if not line.strip():continue
            try:o=json.loads(line)
            except Exception:continue
            n+=1
            if o.get('tender'):tenders+=1
            awards+=len(o.get('awards') or [])
            if len(sample)<3:sample.append({'ocid':o.get('ocid'),'date':o.get('date'),'tag':o.get('tag'),'tender_title':(o.get('tender') or {}).get('title')})
    (OUT/'sample.json').write_text(json.dumps(sample,indent=2,ensure_ascii=False),encoding='utf-8')
    (OUT/'current.jsonl').write_text('',encoding='utf-8')
    stats={'source':'IT_OCP_MIRROR','raw_materialized':n,'tenders_materialized':tenders,'awards_materialized':awards,'current_materialized':0,'lane':'ARCHIVE_MIRROR_OF_ANAC_OCDS','generated_at':NOW.isoformat(),'errors':[],'mirror_url':URL,'bytes':len(body),'provenance':'Open Contracting Data Registry publication Italy ANAC; mirror of ANAC official OCDS, retrieved monthly from dati.anticorruzione.it','anac_official_source':'https://dati.anticorruzione.it/opendata/dataset?q=ocds'}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not n:raise SystemExit(2)
if __name__=='__main__':main()
