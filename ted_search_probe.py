import json, urllib.request
from pathlib import Path
OUT=Path('ted_search'); OUT.mkdir(exist_ok=True)
NOTICES=['561068-2026','551209-2026','560517-2026','562593-2026','561114-2026']
URL='https://api.ted.europa.eu/v3/notices/search'
results=[]
for notice in NOTICES:
    body={
      'query': f'publication-number = {notice}',
      'fields':['publication-number'],
      'page':1,
      'limit':10,
      'scope':'ALL',
      'checkQuerySyntax':False,
      'paginationMode':'PAGE_NUMBER'
    }
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','User-Agent':'TenderEngine/1.0'},method='POST')
    rec={'notice':notice,'status':'UNKNOWN','http_status':None,'response':None,'error':None}
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read(); rec['http_status']=r.status
        txt=raw.decode('utf-8','replace'); rec['response']=json.loads(txt); rec['status']='OK'
    except Exception as e:
        rec['status']='ERROR'; rec['error']=repr(e)
        if hasattr(e,'read'):
            try: rec['response']=e.read().decode('utf-8','replace')
            except Exception: pass
    (OUT/f'{notice}.json').write_text(json.dumps(rec,indent=2,ensure_ascii=False),encoding='utf-8')
    results.append(rec)
print(json.dumps(results,indent=2,ensure_ascii=False))
