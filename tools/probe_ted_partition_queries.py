from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API='https://api.ted.europa.eu/v3/notices/search'
NOW=datetime.now(timezone.utc)
TODAY=NOW.strftime('%Y%m%d')
FIELDS=['publication-number','publication-date','deadline','deadline-receipt-request','deadline-receipt-tender-date-lot','notice-type','form-type']
QUERIES={
    'active_competition':'form-type = competition',
    'generic_deadline_future':f'form-type = competition AND deadline >= {TODAY}',
    'request_deadline_future':f'form-type = competition AND deadline-receipt-request >= {TODAY}',
    'lot_tender_deadline_future':f'form-type = competition AND deadline-receipt-tender-date-lot >= {TODAY}',
    'union_future_deadlines':f'form-type = competition AND (deadline >= {TODAY} OR deadline-receipt-request >= {TODAY} OR deadline-receipt-tender-date-lot >= {TODAY})',
    'oldest_active_publication':'form-type = competition SORT BY publication-date',
    'newest_active_publication':'form-type = competition SORT BY publication-date DESC',
}


def request(session, query):
    body={'query':query,'fields':FIELDS,'limit':1,'scope':'ACTIVE','checkQuerySyntax':False,'paginationMode':'PAGE_NUMBER','page':1}
    last=None
    for attempt in range(4):
        try:
            r=session.post(API,json=body,timeout=(20,60))
            last=r
            if r.status_code in (408,425,429) or r.status_code>=500:
                if attempt<3:
                    time.sleep(2**attempt)
                    continue
            out={'status':r.status_code,'content_type':r.headers.get('content-type'),'bytes':len(r.content)}
            try:
                data=r.json()
                out['keys']=list(data)[:30] if isinstance(data,dict) else None
                if isinstance(data,dict):
                    out['total']=data.get('totalNoticeCount') or data.get('total') or data.get('totalCount')
                    items=data.get('notices') or data.get('results') or data.get('items') or []
                    out['item_count']=len(items) if isinstance(items,list) else None
                    if isinstance(items,list) and items:
                        item=items[0]
                        out['sample']={k:item.get(k) for k in FIELDS if k in item}
                    for key in ('error','errors','message','validationErrors'):
                        if key in data: out[key]=data[key]
                else:
                    out['json_type']=type(data).__name__
            except Exception as exc:
                out['json_error']=repr(exc)
                out['prefix']=r.text[:1000]
            return out
        except Exception as exc:
            last=exc
            if attempt<3:
                time.sleep(2**attempt)
                continue
    return {'exception':repr(last)}


def main():
    s=requests.Session()
    s.headers.update({'Accept':'application/json','Accept-Encoding':'identity','User-Agent':'Tender-Engine/6.7 TED partition probe'})
    results={}
    for name,q in QUERIES.items():
        results[name]={'query':q,**request(s,q)}
    payload={'schema':'TED_PARTITION_QUERY_PROBE_V1','generated_at':NOW.isoformat(),'today':TODAY,'results':results}
    Path('control').mkdir(exist_ok=True)
    Path('control/ted_partition_probe.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
