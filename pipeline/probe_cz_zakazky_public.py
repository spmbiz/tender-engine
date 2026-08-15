from __future__ import annotations

import json, os
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/CZ_ZAKAZKY_GOV'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://zakazky.gov.cz/'
API='https://api.isd.nipez.cz/isd/seznam/zakazek/hlavni-seznam'
DAY_API='https://api.isd.nipez.cz/isd/seznam/zakazek/zakazky-za-24-hodin'
NOW=datetime.now(timezone.utc)
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.1 (+public procurement research)','Accept':'application/json, text/plain, */*','Content-Type':'application/json','Origin':'https://zakazky.gov.cz','Referer':'https://zakazky.gov.cz/'})

def shape(data):
    if isinstance(data,dict):return {'type':'dict','keys':list(data.keys())[:100],**{k:len(v) for k,v in data.items() if isinstance(v,list)}}
    if isinstance(data,list):return {'type':'list','length':len(data)}
    return {'type':type(data).__name__}

def bounded(data,limit=700000):
    raw=json.dumps(data,ensure_ascii=False)
    return {'shape':shape(data),'data':data if len(raw)<=limit else None,'data_preview':None if len(raw)<=limit else raw[:limit],'bytes_json':len(raw)}

def main():
    payload={'clearCache':True,'filters':[],'pagination':{'length':10,'start':0},'sort':[{'field':'datumUverejneniVvz','primitiveType':'date','type':'DESC'}]}
    attempts=[];samples=[]
    try:
        r=S.post(API,json=payload,timeout=45);attempts.append({'url':API,'method':'POST','status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')})
        if r.status_code==200:
            try:samples.append({'url':API,'status':200,**bounded(r.json())})
            except Exception as exc:samples.append({'url':API,'status':200,'parse_error':repr(exc),'text_preview':r.text[:4000]})
        else:samples.append({'url':API,'status':r.status_code,'text_preview':r.text[:4000]})
    except Exception as exc:attempts.append({'url':API,'method':'POST','error':repr(exc)})
    try:
        r=S.get(DAY_API,timeout=45);attempts.append({'url':DAY_API,'method':'GET','status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')})
        if r.status_code==200:
            try:samples.append({'url':DAY_API,'status':200,**bounded(r.json())})
            except Exception as exc:samples.append({'url':DAY_API,'status':200,'parse_error':repr(exc),'text_preview':r.text[:4000]})
        else:samples.append({'url':DAY_API,'status':r.status_code,'text_preview':r.text[:4000]})
    except Exception as exc:attempts.append({'url':DAY_API,'method':'GET','error':repr(exc)})
    good=[x for x in samples if x.get('status')==200 and x.get('shape')]
    probe={'source':'CZ_ZAKAZKY_GOV','generated_at':NOW.isoformat(),'official_url':BASE,'main_api':API,'day_api':DAY_API,'request_payload':payload,'attempts':attempts,'public_json_samples':samples}
    (OUT/'probe.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={'source':'CZ_ZAKAZKY_GOV','raw_materialized':0,'current_materialized':0,'probe_only':True,'public_json_samples':len(good),'generated_at':NOW.isoformat(),'errors':[] if good else [{'type':'NO_PUBLIC_PROCUREMENT_JSON_CAPTURED'}],'official_url':BASE,'main_api':API,'day_api':DAY_API,'attempts':attempts}
    (OUT/'stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(stats,ensure_ascii=False,indent=2));print('PUBLIC_JSON',json.dumps(samples,ensure_ascii=False,indent=2)[:900000])
    if not good:raise SystemExit(2)
if __name__=='__main__':main()
