from __future__ import annotations

import json, os
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/IT_ANAC_OCDS_BULK'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);MONTHS=max(6,min(36,int(os.getenv('IT_PROBE_MONTHS','24'))));DOWNLOAD_MAX=int(os.getenv('IT_DOWNLOAD_MAX_BYTES','250000000'))
BASE='https://dati.anticorruzione.it/opendata/download/dataset/ocds/filesystem/bulk/{year}/{month:02d}.json'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/4.8 (+public procurement research)','Accept':'application/json,*/*'})
def month_iter():
    y,m=NOW.year,NOW.month
    for _ in range(MONTHS):
        yield y,m
        m-=1
        if m==0:y-=1;m=12
def count_releases(data):
    if isinstance(data,list):return len(data)
    if isinstance(data,dict):
        for k in ('releases','records','data','items'):
            if isinstance(data.get(k),list):return len(data[k])
    return 0
def main():
    inv=[];downloaded=[];latest=None
    for y,m in month_iter():
        url=BASE.format(year=y,month=m)
        try:r=S.get(url,timeout=90,stream=True)
        except Exception as exc:inv.append({'year':y,'month':m,'url':url,'error':repr(exc)});continue
        size=int(r.headers.get('content-length') or 0);rec={'year':y,'month':m,'url':url,'status':r.status_code,'content_length':size,'content_type':r.headers.get('content-type')};inv.append(rec)
        if r.status_code!=200:continue
        if latest is None:latest=(y,m,url,size)
        # Persist a bounded sample/full file when reasonable; inventory all existing months regardless.
        if size and size>DOWNLOAD_MAX:continue
        try:
            body=r.content
            if len(body)>DOWNLOAD_MAX:continue
            p=OUT/f'ocds_{y}_{m:02d}.json';p.write_bytes(body)
            try:data=json.loads(body);n=count_releases(data)
            except Exception:n=None
            downloaded.append({'year':y,'month':m,'file':p.name,'bytes':len(body),'release_count':n})
            # one newest bulk is enough for recurrent smoke; historical backfill can enumerate inventory separately.
            if len(downloaded)>=1:break
        except Exception as exc:rec['download_error']=repr(exc)
    (OUT/'resource_inventory.json').write_text(json.dumps(inv,indent=2,ensure_ascii=False),encoding='utf-8')
    (OUT/'current.jsonl').write_text('',encoding='utf-8')
    stats={'source':'IT_ANAC_OCDS_BULK','raw_materialized':sum(x.get('release_count') or 0 for x in downloaded),'current_materialized':0,'lane':'ARCHIVE_OCDS_MONTHLY_BULK','generated_at':NOW.isoformat(),'errors':[] if latest else [{'type':'NO_AVAILABLE_MONTH_IN_PROBE_WINDOW'}],'official_pattern':BASE,'latest_available':{'year':latest[0],'month':latest[1],'url':latest[2],'bytes_header':latest[3]} if latest else None,'downloaded':downloaded,'inventory_count':len(inv)}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not latest:raise SystemExit(2)
if __name__=='__main__':main()
