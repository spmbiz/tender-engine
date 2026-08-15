from __future__ import annotations

import json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/PT_BASE_OPEN'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);LOOKBACK=max(7,min(120,int(os.getenv('LOOKBACK_DAYS','45'))));MAX_BYTES=int(os.getenv('PT_MAX_BYTES','250000000'))
API='https://dados.gov.pt/api/1/datasets/'
QUERY='Contratos Públicos Portal Base IMPIC Anúncios 2012 2026'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.4 (+public procurement research)','Accept':'application/json,*/*'})

def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    for fmt in ('%d/%m/%Y %H:%M','%d/%m/%Y','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S','%Y-%m-%d'):
        try:
            x=datetime.strptime(s[:25],fmt);return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
        except Exception:pass
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None

def flat_values(o):
    out={}
    def walk(x,p=''):
        if isinstance(x,dict):
            for k,v in x.items():walk(v,(p+'.'+str(k)).strip('.'))
        elif isinstance(x,list):
            if all(not isinstance(v,(dict,list)) for v in x):out[p]=x
            else:
                for i,v in enumerate(x):walk(v,f'{p}[{i}]')
        else:out[p]=x
    walk(o);return out

def first(flat,*needles):
    for n in needles:
        nl=n.lower().replace('_','').replace('-','')
        for k,v in flat.items():
            kl=k.lower().replace('_','').replace('-','')
            if kl.endswith(nl) and v not in (None,'',[]):return v
    return None

def iter_rows(data):
    if isinstance(data,list):yield from (x for x in data if isinstance(x,dict));return
    if isinstance(data,dict):
        for k in ('data','items','results','anuncios','announcements','records'):
            v=data.get(k)
            if isinstance(v,list):yield from (x for x in v if isinstance(x,dict));return
        # Some annual files are keyed by record id.
        vals=[v for v in data.values() if isinstance(v,dict)]
        if vals:yield from vals

def dataset_candidates():
    tele=[];datasets=[]
    probes=[{'q':QUERY,'page_size':20},{'q':'Anúncios de 2012 a 2026','page_size':20},{'q':'Portal Base IMPIC Anúncios','page_size':50}]
    for p in probes:
        try:r=S.get(API,params=p,timeout=60);tele.append({'url':r.url,'status':r.status_code,'bytes':len(r.content)})
        except Exception as exc:tele.append({'probe':p,'error':repr(exc)});continue
        if not r.ok:continue
        try:d=r.json()
        except Exception:continue
        arr=d.get('data') if isinstance(d,dict) else d
        if isinstance(arr,list):datasets.extend(x for x in arr if isinstance(x,dict))
    # Stable detail endpoint by known public slug if search API is partial.
    slug='contratos-publicos-portal-base-impic-anuncios-de-2012-a-2026'
    for url in (API+slug+'/',API+slug):
        try:r=S.get(url,timeout=60);tele.append({'url':r.url,'status':r.status_code,'bytes':len(r.content)})
        except Exception as exc:tele.append({'url':url,'error':repr(exc)});continue
        if r.ok:
            try:
                d=r.json();
                if isinstance(d,dict):datasets.append(d)
            except Exception:pass
    return datasets,tele

def choose_resource(datasets):
    c=[]
    for d in datasets:
        title=clean(d.get('title') or d.get('name'))
        if 'an' not in title.lower() or '2026' not in title.lower():continue
        for r in d.get('resources') or []:
            if not isinstance(r,dict):continue
            name=clean(r.get('title') or r.get('name') or r.get('description'));fmt=clean(r.get('format') or r.get('mime'))
            url=r.get('url') or r.get('latest')
            if not isinstance(url,str):continue
            score=(10 if '2026' in name else 0)+(8 if 'json' in (fmt+' '+name+url).lower() else 0)+(2 if 'anuncio' in name.lower() else 0)
            c.append((score,name,fmt,url,d.get('id') or d.get('slug')))
    c.sort(reverse=True,key=lambda x:x[0]);return c

def main():
    datasets,tele=dataset_candidates();resources=choose_resource(datasets)
    if not resources:
        stats={'source':'PT_BASE_OPEN','raw_materialized':0,'current_materialized':0,'generated_at':NOW.isoformat(),'errors':[{'type':'NO_2026_OPEN_RESOURCE'}],'telemetry':tele};(OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False));print(json.dumps(stats,indent=2));raise SystemExit(2)
    selected=None;data=None
    for score,name,fmt,url,did in resources[:12]:
        try:r=S.get(url,timeout=180,allow_redirects=True);tele.append({'resource':name,'url':url,'resolved_url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')})
        except Exception as exc:tele.append({'resource':name,'url':url,'error':repr(exc)});continue
        if not r.ok or not r.content or len(r.content)>MAX_BYTES:continue
        try:data=r.json()
        except Exception:
            try:data=json.loads(r.content.decode('utf-8-sig'))
            except Exception:continue
        if any(True for _ in iter_rows(data)):
            selected={'name':name,'format':fmt,'url':url,'resolved_url':r.url,'bytes':len(r.content),'dataset_id':did};break
    if data is None:
        stats={'source':'PT_BASE_OPEN','raw_materialized':0,'current_materialized':0,'generated_at':NOW.isoformat(),'errors':[{'type':'NO_PARSEABLE_2026_RESOURCE'}],'resources':resources[:20],'telemetry':tele};(OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False));print(json.dumps(stats,indent=2));raise SystemExit(2)
    rows=[]
    outcome_words=('adjudic','resultado','award','celebra','contrato celebrado','modifica')
    for o in iter_rows(data):
        f=flat_values(o)
        nid=clean(first(f,'nAnuncio','numeroAnuncio','idAnuncio','id','numero'))
        title=clean(first(f,'objectoContrato','objetoContrato','designacao','descricao','titulo','description','object'))
        typ=clean(first(f,'tipoAnuncio','tipoprocedimento','tipoProcedimento','type'))
        pub=pdt(first(f,'dataPublicacao','publicationDate','datePublished','data'))
        deadline=pdt(first(f,'dataLimite','deadline','dataLimiteEntrega','prazoApresentacao','submissionDeadline'))
        buyer=clean(first(f,'adjudicante','entidadeAdjudicante','contractingEntity','buyer'))
        urls=[]
        for k,v in f.items():
            vals=v if isinstance(v,list) else [v]
            for z in vals:
                if isinstance(z,str) and z.startswith('http') and z not in urls:urls.append(z)
        docs=[u for u in urls if re.search(r'(pecas|document|\.pdf|\.zip|\.docx?)',u,re.I)]
        detail=next((u for u in urls if 'base.gov.pt' in u.lower()),None)
        rid=nid or str(abs(hash((title,buyer,str(pub),str(o)[:500]))))
        is_notice=not any(w in (typ+' '+title).lower() for w in outcome_words)
        current=bool(is_notice and ((deadline and deadline>=NOW) or (not deadline and pub and pub>=NOW-timedelta(days=LOOKBACK))))
        if not (nid or title):continue
        rows.append({'candidate_id':f'PT-BASE:{rid}','source':'PT_BASE_OPEN','portal':'PT_BASE','notice_id':nid or None,'title':title or rid,'buyer':buyer or None,'deadline':deadline.isoformat() if deadline else None,'published':pub.isoformat() if pub else None,'current':current,'notice_url':detail,'description':'','announcement_type':typ or None,'route':{'document_urls':docs,'detail_url':detail,'public_urls':urls[:30]},'source_resource':selected,'discovered_at':NOW.isoformat()})
    seen={}
    for x in rows:seen[x['candidate_id']]=x
    rows=list(seen.values());cur=[x for x in rows if x['current']]
    for fn,arr in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as fp:
            for x in arr:fp.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'PT_BASE_OPEN','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'published_parsed':sum(bool(x['published']) for x in rows),'document_routes':sum(bool(x['route']['document_urls']) for x in rows),'lookback_days':LOOKBACK,'generated_at':NOW.isoformat(),'errors':[],'selected_resource':selected,'resource_candidates':resources[:20],'telemetry':tele,'official_dataset':'https://dados.gov.pt/datasets/contratos-publicos-portal-base-impic-anuncios-de-2012-a-2026'}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False));print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
