from __future__ import annotations

import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/IT_ANAC_OCDS_BULK'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc)
YEARS=max(2,min(12,int(os.getenv('IT_PROBE_YEARS','6'))))
DOWNLOAD_MAX=int(os.getenv('IT_DOWNLOAD_MAX_BYTES','650000000'))
DOWNLOAD_RESOURCES=max(0,min(12,int(os.getenv('IT_DOWNLOAD_RESOURCES','1'))))
CKAN='https://dati.anticorruzione.it/opendata/api/3/action/package_show'
LEGACY='https://dati.anticorruzione.it/opendata/download/dataset/ocds/filesystem/bulk/{year}/{month:02d}.json'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.1 (+public procurement research)','Accept':'application/json,*/*'})

def count_releases(data):
    if isinstance(data,list):return len(data)
    if isinstance(data,dict):
        for k in ('releases','records','data','items'):
            if isinstance(data.get(k),list):return len(data[k])
    return 0

def resource_rank(r:dict):
    text=' '.join(str(r.get(k) or '') for k in ('name','description','url')).lower()
    m=re.search(r'(?<!\d)(20\d{2})[_\-/ .](0?[1-9]|1[0-2])(?!\d)',text)
    ym=(int(m.group(1)),int(m.group(2))) if m else (int(r.get('package_year') or 0),0)
    stamp=str(r.get('last_modified') or r.get('created') or '')
    return (ym[0],ym[1],stamp,str(r.get('name') or ''))

def is_json_resource(r:dict):
    fmt=str(r.get('format') or '').lower()
    url=str(r.get('url') or '').lower()
    name=str(r.get('name') or '').lower()
    return fmt=='json' or '.json' in url or 'json' in name

def fetch_package(year:int):
    pid=f'ocds-appalti-ordinari-{year}'
    try:
        r=S.get(CKAN,params={'id':pid},timeout=75)
        rec={'year':year,'package_id':pid,'url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')}
        if not r.ok:return rec,None
        data=r.json()
        if not data.get('success') or not isinstance(data.get('result'),dict):return rec,None
        return rec,data['result']
    except Exception as exc:return {'year':year,'package_id':pid,'error':repr(exc)},None

def download_resource(rsrc:dict,idx:int):
    url=str(rsrc.get('url') or '').strip()
    if not url:return {'resource_id':rsrc.get('id'),'error':'NO_URL'}
    name=str(rsrc.get('name') or f'resource_{idx}');safe=re.sub(r'[^A-Za-z0-9._-]+','_',name).strip('_')[:120] or f'resource_{idx}'
    if not safe.lower().endswith('.json'):safe+='.json'
    path=OUT/safe
    try:
        with S.get(url,timeout=180,stream=True,allow_redirects=True) as resp:
            meta={'resource_id':rsrc.get('id'),'name':rsrc.get('name'),'url':url,'resolved_url':resp.url,'status':resp.status_code,'content_type':resp.headers.get('content-type'),'content_length':int(resp.headers.get('content-length') or 0)}
            if not resp.ok:return meta
            if meta['content_length'] and meta['content_length']>DOWNLOAD_MAX:
                meta['skipped']='CONTENT_LENGTH_OVER_CAP';return meta
            total=0
            with path.open('wb') as f:
                for chunk in resp.iter_content(1024*1024):
                    if not chunk:continue
                    total+=len(chunk)
                    if total>DOWNLOAD_MAX:
                        f.close();path.unlink(missing_ok=True);meta['skipped']='STREAM_OVER_CAP';meta['bytes_seen']=total;return meta
                    f.write(chunk)
            meta['file']=path.name;meta['bytes']=total
        try:
            data=json.loads(path.read_bytes());meta['release_count']=count_releases(data)
        except Exception as exc:meta['parse_error']=repr(exc);meta['release_count']=None
        return meta
    except Exception as exc:return {'resource_id':rsrc.get('id'),'name':rsrc.get('name'),'url':url,'error':repr(exc)}

def legacy_probe():
    inv=[]
    # The old filesystem layout is known to exist for historical years; scan broadly only if CKAN metadata fails.
    for y in range(min(NOW.year,2023),2016,-1):
        for m in range(12,0,-1):
            url=LEGACY.format(year=y,month=m)
            try:r=S.get(url,timeout=45,stream=True);inv.append({'year':y,'month':m,'url':url,'status':r.status_code,'content_length':int(r.headers.get('content-length') or 0),'content_type':r.headers.get('content-type')})
            except Exception as exc:inv.append({'year':y,'month':m,'url':url,'error':repr(exc)});continue
            if r.status_code==200:return inv,inv[-1]
    return inv,None

def main():
    years=list(range(NOW.year,NOW.year-YEARS,-1))
    package_inventory=[];resources=[]
    for y in years:
        rec,pkg=fetch_package(y);package_inventory.append(rec)
        if not pkg:continue
        for r in pkg.get('resources') or []:
            if not isinstance(r,dict) or not is_json_resource(r):continue
            rr={k:r.get(k) for k in ('id','name','format','url','created','last_modified','size','description')}
            rr['package_year']=y;resources.append(rr)
    resources.sort(key=resource_rank,reverse=True)
    downloaded=[]
    for i,r in enumerate(resources[:max(DOWNLOAD_RESOURCES,1)]):
        if len(downloaded)>=DOWNLOAD_RESOURCES:break
        downloaded.append(download_resource(r,i))
    fallback_inventory=[];fallback_hit=None
    if not resources:fallback_inventory,fallback_hit=legacy_probe()
    (OUT/'package_inventory.json').write_text(json.dumps(package_inventory,indent=2,ensure_ascii=False),encoding='utf-8')
    (OUT/'resource_inventory.json').write_text(json.dumps(resources or fallback_inventory,indent=2,ensure_ascii=False),encoding='utf-8')
    (OUT/'current.jsonl').write_text('',encoding='utf-8')
    available=bool(resources or fallback_hit)
    stats={
      'source':'IT_ANAC_OCDS_BULK','raw_materialized':sum(x.get('release_count') or 0 for x in downloaded),
      'current_materialized':0,'lane':'ARCHIVE_OCDS_MONTHLY_BULK','generated_at':NOW.isoformat(),
      'errors':[] if available else [{'type':'NO_AVAILABLE_OCDS_RESOURCE'}],
      'official_ckan_api':CKAN,'package_pattern':'ocds-appalti-ordinari-{year}','legacy_pattern':LEGACY,
      'package_inventory_count':len(package_inventory),'json_resource_count':len(resources),
      'latest_resource':resources[0] if resources else fallback_hit,'downloaded':downloaded,
      'download_cap_bytes':DOWNLOAD_MAX,'download_resources_requested':DOWNLOAD_RESOURCES,
      'semantics':'Archive evidence lane. Current live competition discovery remains separate; do not treat these monthly OCDS packages as a live-open-opportunity feed.'
    }
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not available:raise SystemExit(2)
if __name__=='__main__':main()
