from pathlib import Path
import json, re, xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

OUT=Path('ted_routes'); OUT.mkdir(exist_ok=True)
CASES={
 'ETF':'561068-2026',
 'GRONINGEN':'551209-2026',
 'APEC':'560517-2026',
 'MISTRA':'562593-2026',
 'BOSA':'561114-2026',
}

def fetch(url):
    req=Request(url,headers={'User-Agent':'TenderEngine/1.0'})
    with urlopen(req,timeout=45) as r: return r.read(), dict(r.headers)

def local(tag): return tag.rsplit('}',1)[-1]

def extract(xml_bytes):
    root=ET.fromstring(xml_bytes)
    refs=[]; all_uris=[]
    for el in root.iter():
        if local(el.tag)=='URI' and el.text and el.text.strip().startswith(('http://','https://')):
            all_uris.append(el.text.strip())
    # Traverse CallForTendersDocumentReference and capture URI + DocumentType
    for ref in root.iter():
        if local(ref.tag)!='CallForTendersDocumentReference': continue
        rec={'document_types':[],'ids':[],'uris':[]}
        for x in ref.iter():
            n=local(x.tag); txt=(x.text or '').strip()
            if not txt: continue
            if n=='DocumentType': rec['document_types'].append(txt)
            elif n=='ID': rec['ids'].append(txt)
            elif n=='URI' and txt.startswith(('http://','https://')): rec['uris'].append(txt)
        if rec['uris']: refs.append(rec)
    return refs, list(dict.fromkeys(all_uris))

summary=[]
for key,notice in CASES.items():
    url=f'https://ted.europa.eu/en/notice/{notice}/xml'
    rec={'key':key,'notice':notice,'xml_url':url,'status':'UNKNOWN','bt15':[],'all_uris':[],'error':None}
    try:
        data,headers=fetch(url)
        (OUT/f'{key}.xml').write_bytes(data)
        refs,uris=extract(data)
        rec['bt15']=refs; rec['all_uris']=uris; rec['status']='OK'
    except Exception as e:
        rec['status']='ERROR'; rec['error']=repr(e)
    (OUT/f'{key}.json').write_text(json.dumps(rec,indent=2,ensure_ascii=False),encoding='utf-8')
    summary.append(rec)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
