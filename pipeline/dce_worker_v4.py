from __future__ import annotations

import copy
import re
from pathlib import Path

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v3 as v3


def _route_urls(candidate: dict) -> list[tuple[str, str]]:
    route=candidate.get('route') or {}; out=[]
    def add(method,u):
        if isinstance(u,str) and u.startswith(('http://','https://')):out.append((method,u))
    for u in route.get('document_urls') or []:add('DIRECT_DOCUMENT',u)
    for d in candidate.get('documents') or []:
        if isinstance(d,str):add('DIRECT_DOCUMENT',d)
        elif isinstance(d,dict):add('DIRECT_DOCUMENT',d.get('url'))
    add('NOTICE_PAGE',candidate.get('notice_url'))
    for k in ('detail_url','proceeding_url','competition_docs_url','publication_details_url','documents_url','header_url','public_url','source_url','additional_info_url'):
        add(k.upper(),route.get(k))
    for k,v in route.items():
        if k not in ('document_urls','detail_url','proceeding_url','competition_docs_url','publication_details_url','documents_url','header_url','public_url','source_url','additional_info_url','document_download_template','tender_api_url'):
            add(f'ROUTE_{k.upper()}',v)
    for u in re.findall(r'https?://[^\s<>"\']+',str(candidate.get('description') or ''))[:10]:add('DESCRIPTION_URL',u.rstrip(').,;'))
    seen=set();uniq=[]
    for m,u in out:
        if u not in seen:seen.add(u);uniq.append((m,u))
    return uniq


def _attempt_direct(candidate: dict,out:Path,manifest:dict) -> bool:
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/5.0 public procurement research'})
    got=False
    for method,url in _route_urls(candidate):
        if method!='DIRECT_DOCUMENT':continue
        rec=base.direct_download(url,out,session)
        manifest.setdefault('dce_method_attempts',[]).append({'method':method,'url':url,'outcome':'DOWNLOADED' if rec else 'NOT_FILE'})
        if rec:manifest['files'].append(rec);got=True
    return got


def _try_page(candidate:dict,url:str,out:Path,manifest:dict,method:str)->str:
    trial=copy.deepcopy(candidate);trial['notice_url']=url
    troute=dict(trial.get('route') or {});troute['detail_url']=url;trial['route']=troute
    tmp={'files':[]};v3._public_page_adapter(trial,out,tmp)
    for f in tmp.get('files') or []:manifest['files'].append(f)
    status=tmp.get('status') or 'UNKNOWN'
    manifest.setdefault('dce_method_attempts',[]).append({'method':method,'url':url,'outcome':status,'document_candidates':tmp.get('public_document_candidates',[])[:15],'error':tmp.get('error')})
    return status


def cascade_public_adapter(candidate: dict,out:Path,manifest:dict):
    manifest.setdefault('dce_method_attempts',[])
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    statuses=[]
    for method,url in _route_urls(candidate):
        if method=='DIRECT_DOCUMENT':continue
        status=_try_page(candidate,url,out,manifest,method);statuses.append(status)
        if manifest['files']:manifest['status']='DOWNLOADED_PUBLIC';return
    priority=['CAPTCHA_REQUIRED','AUTH_REQUIRED','ERROR_RETRYABLE','ROUTE_INCOMPLETE','NO_PUBLIC_FILE']
    final=next((s for s in priority if s in statuses),'GENERIC_PUBLIC_PAGE_UNRESOLVED')
    if final=='NO_PUBLIC_FILE':final='GENERIC_PUBLIC_PAGE_UNRESOLVED'
    manifest['status']=final


def adapter_greece(candidate:dict,out:Path,manifest:dict):
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    cascade_public_adapter(candidate,out,manifest)


def _pl_document_nodes(obj):
    """Yield likely public procurement document descriptors from GetTender JSON."""
    if isinstance(obj,dict):
        low={str(k).lower():v for k,v in obj.items()}
        fname=next((low.get(k) for k in ('filename','file_name','name','documentname','originalfilename','title') if low.get(k)),None)
        did=next((low.get(k) for k in ('documentid','document_id','fileid','file_id','id') if low.get(k)),None)
        if fname and did and re.search(r'\.(pdf|zip|7z|rar|docx?|xlsx?|xls|pptx?|odt|ods|xml|txt)$',str(fname),re.I):
            yield {'id':str(did),'name':str(fname)}
        for v in obj.values():yield from _pl_document_nodes(v)
    elif isinstance(obj,list):
        for v in obj:yield from _pl_document_nodes(v)


def _pl_api_download(candidate:dict,out:Path,manifest:dict,session:requests.Session)->bool:
    route=candidate.get('route') or {};api=route.get('tender_api_url');tender_id=str(route.get('tender_id') or candidate.get('tender_id') or '').strip();template=route.get('document_download_template')
    if not api or not tender_id:return False
    try:
        r=session.get(api,timeout=60);manifest.setdefault('dce_method_attempts',[]).append({'method':'PL_GET_TENDER_API','url':api,'http_status':r.status_code,'bytes':len(r.content)})
        if not r.ok:return False
        data=r.json();nodes=[];seen=set()
        for n in _pl_document_nodes(data):
            key=(n['id'],n['name'])
            if key not in seen:seen.add(key);nodes.append(n)
        manifest['pl_tender_document_descriptors']=nodes[:300]
        got=False
        for n in nodes[:200]:
            url=(template or f'https://ezamowienia.gov.pl/mp-readmodels/api/Tender/DownloadDocument/{tender_id}/{{document_id}}').replace('{document_id}',requests.utils.quote(n['id'],safe=''))
            rec=base.direct_download(url,out,session)
            manifest['dce_method_attempts'].append({'method':'PL_DIRECT_DOCUMENT_API','url':url,'document_name':n['name'],'outcome':'DOWNLOADED' if rec else 'NOT_FILE'})
            if rec:manifest['files'].append(rec);got=True
        return got
    except Exception as exc:
        manifest.setdefault('dce_method_attempts',[]).append({'method':'PL_GET_TENDER_API','url':api,'error':repr(exc)});return False


def adapter_poland(candidate:dict,out:Path,manifest:dict):
    manifest.setdefault('dce_method_attempts',[])
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/5.0 public procurement research'})
    if _pl_api_download(candidate,out,manifest,session):manifest['status']='DOWNLOADED_PUBLIC';return
    routes=_route_urls(candidate);extra=[]
    for method,url in routes:
        if method=='DIRECT_DOCUMENT':continue
        try:
            r=session.get(url,timeout=45,allow_redirects=True);manifest['dce_method_attempts'].append({'method':'PL_RESOLVE_PROCEEDING','url':url,'http_status':r.status_code})
            if r.ok:
                for u in re.findall(r'https?://ezamowienia\.gov\.pl/mp-client/search/list/ocds-[A-Za-z0-9-]+',r.text,re.I):extra.append(('PL_PROCEEDING',u))
                for u in re.findall(r'https?://[^\s"\'<>]+',r.text):
                    if any(h in u.lower() for h in ('platformazakupowa.pl','logintrade.net','smartpzp.pl','e-propublico.pl','ezamawiajacy.pl','josephine.proebiz.com')):extra.append(('PL_EXTERNAL_PROCEEDING',u.rstrip(').,;')))
        except Exception as exc:manifest['dce_method_attempts'].append({'method':'PL_RESOLVE_PROCEEDING','url':url,'error':repr(exc)})
    seen=set();statuses=[]
    for method,url in routes+extra:
        if method=='DIRECT_DOCUMENT' or url in seen:continue
        seen.add(url);status=_try_page(candidate,url,out,manifest,method);statuses.append(status)
        if manifest['files']:manifest['status']='DOWNLOADED_PUBLIC';return
    priority=['CAPTCHA_REQUIRED','AUTH_REQUIRED','ERROR_RETRYABLE','ROUTE_INCOMPLETE']
    manifest['status']=next((s for s in priority if s in statuses),'GENERIC_PUBLIC_PAGE_UNRESOLVED')


for portal in ('GENERIC_PUBLIC_PAGE','CA_CANADABUYS','QC_SEAO','DE_DOE','FR_BOAMP','NZ_GETS','AU_AUSTENDER','US_SAM','US_SAM_BULK','NL_TENDERNED','NL_TENDERNED_RSS','CH_SIMAP','LV_IUB','NO_DOFFIN'):
    base.ADAPTERS[portal]=cascade_public_adapter
for portal in ('PL_EZAMOWIENIA','PL_BZP'):base.ADAPTERS[portal]=adapter_poland
base.ADAPTERS['GR_KHMDHS']=adapter_greece

if __name__=='__main__':v2.main()
