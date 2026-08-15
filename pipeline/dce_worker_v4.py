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
        if k not in ('document_urls','detail_url','proceeding_url','competition_docs_url','publication_details_url','documents_url','header_url','public_url','source_url','additional_info_url'):
            add(f'ROUTE_{k.upper()}',v)
    for u in re.findall(r'https?://[^\s<>"\']+',str(candidate.get('description') or ''))[:10]:add('DESCRIPTION_URL',u.rstrip(').,;'))
    seen=set();uniq=[]
    for m,u in out:
        if u not in seen:seen.add(u);uniq.append((m,u))
    return uniq


def _attempt_direct(candidate: dict,out:Path,manifest:dict) -> bool:
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/4.8 public procurement research'})
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
    """Try every lawful public route before declaring a portal unresolved.

    explicit files -> notice/detail/proceeding URLs -> HTTP anchors -> rendered
    browser anchors. Login/CAPTCHA/MFA are terminal evidence, never bypassed.
    """
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


def adapter_poland(candidate:dict,out:Path,manifest:dict):
    """BZP notice -> public proceeding page -> actual SWZ/attachments.

    The BZP notice explicitly publishes the procedure address. When discovery
    has not extracted it yet, resolve that public link from notice HTML and
    then run the normal HTTP+browser document cascade on the proceeding page.
    """
    manifest.setdefault('dce_method_attempts',[])
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    routes=_route_urls(candidate);extra=[];session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/4.8 public procurement research'})
    for method,url in routes:
        if method=='DIRECT_DOCUMENT':continue
        try:
            r=session.get(url,timeout=45,allow_redirects=True)
            manifest['dce_method_attempts'].append({'method':'PL_RESOLVE_PROCEEDING','url':url,'http_status':r.status_code})
            if r.ok:
                for u in re.findall(r'https?://ezamowienia\.gov\.pl/mp-client/search/list/ocds-[A-Za-z0-9-]+',r.text,re.I):extra.append(('PL_PROCEEDING',u))
                for u in re.findall(r'https?://[^\s"\'<>]+',r.text):
                    if any(h in u.lower() for h in ('platformazakupowa.pl','logintrade.net','smartpzp.pl','e-propublico.pl','ezamawiajacy.pl','josephine.proebiz.com')):extra.append(('PL_EXTERNAL_PROCEEDING',u.rstrip(').,;')))
        except Exception as exc:manifest['dce_method_attempts'].append({'method':'PL_RESOLVE_PROCEEDING','url':url,'error':repr(exc)})
    all_routes=routes+extra;seen=set();statuses=[]
    for method,url in all_routes:
        if method=='DIRECT_DOCUMENT' or url in seen:continue
        seen.add(url);status=_try_page(candidate,url,out,manifest,method);statuses.append(status)
        if manifest['files']:manifest['status']='DOWNLOADED_PUBLIC';return
    priority=['CAPTCHA_REQUIRED','AUTH_REQUIRED','ERROR_RETRYABLE','ROUTE_INCOMPLETE']
    manifest['status']=next((s for s in priority if s in statuses),'GENERIC_PUBLIC_PAGE_UNRESOLVED')


for portal in (
    'GENERIC_PUBLIC_PAGE','CA_CANADABUYS','QC_SEAO','DE_DOE','FR_BOAMP','NZ_GETS','AU_AUSTENDER',
    'US_SAM','US_SAM_BULK','NL_TENDERNED','NL_TENDERNED_RSS','CH_SIMAP','LV_IUB','NO_DOFFIN',
):base.ADAPTERS[portal]=cascade_public_adapter
for portal in ('PL_EZAMOWIENIA','PL_BZP'):base.ADAPTERS[portal]=adapter_poland
base.ADAPTERS['GR_KHMDHS']=adapter_greece

if __name__=='__main__':v2.main()
