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
    for k in ('detail_url','proceeding_url','documents_url','header_url','public_url','source_url','additional_info_url'):
        add(k.upper(),route.get(k))
    # Some sources expose useful public URLs in scalar route fields under evolving names.
    for k,v in route.items():
        if k not in ('document_urls','detail_url','proceeding_url','documents_url','header_url','public_url','source_url','additional_info_url'):
            add(f'ROUTE_{k.upper()}',v)
    # URLs embedded in descriptions occasionally carry the actual buyer platform.
    for u in re.findall(r'https?://[^\s<>"\']+',str(candidate.get('description') or ''))[:10]:add('DESCRIPTION_URL',u.rstrip(').,;'))
    seen=set();uniq=[]
    for m,u in out:
        if u not in seen:seen.add(u);uniq.append((m,u))
    return uniq


def _attempt_direct(candidate: dict,out:Path,manifest:dict) -> bool:
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/4.6 public procurement research'})
    got=False
    for method,url in _route_urls(candidate):
        if method!='DIRECT_DOCUMENT':continue
        rec=base.direct_download(url,out,session)
        manifest.setdefault('dce_method_attempts',[]).append({'method':method,'url':url,'outcome':'DOWNLOADED' if rec else 'NOT_FILE'})
        if rec:
            manifest['files'].append(rec);got=True
    return got


def cascade_public_adapter(candidate: dict,out:Path,manifest:dict):
    """Try every lawful public route before declaring a Western portal unresolved.

    Order: explicit document URLs -> notice/detail/proceeding/header URLs via HTTP
    anchor discovery -> browser JS anchor discovery (inside v3). We never bypass
    login, CAPTCHA, MFA or access controls. Every attempted route is preserved.
    """
    manifest.setdefault('dce_method_attempts',[])
    if _attempt_direct(candidate,out,manifest):
        manifest['status']='DOWNLOADED_PUBLIC';return
    statuses=[]
    for method,url in _route_urls(candidate):
        if method=='DIRECT_DOCUMENT':continue
        trial=copy.deepcopy(candidate);trial['notice_url']=url
        troute=dict(trial.get('route') or {});troute['detail_url']=url;trial['route']=troute
        tmp={'files':[]}
        v3._public_page_adapter(trial,out,tmp)
        for f in tmp.get('files') or []:manifest['files'].append(f)
        status=tmp.get('status') or 'UNKNOWN';statuses.append(status)
        manifest['dce_method_attempts'].append({'method':method,'url':url,'outcome':status,'document_candidates':tmp.get('public_document_candidates',[])[:10],'error':tmp.get('error')})
        if manifest['files']:
            manifest['status']='DOWNLOADED_PUBLIC';return
    priority=['CAPTCHA_REQUIRED','AUTH_REQUIRED','ERROR_RETRYABLE','ROUTE_INCOMPLETE','NO_PUBLIC_FILE']
    final=next((s for s in priority if s in statuses),'GENERIC_PUBLIC_PAGE_UNRESOLVED')
    if final=='NO_PUBLIC_FILE':final='GENERIC_PUBLIC_PAGE_UNRESOLVED'
    manifest['status']=final


def adapter_greece(candidate:dict,out:Path,manifest:dict):
    # KIMDIS publishes a direct public attachment PDF by reference number.
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    cascade_public_adapter(candidate,out,manifest)


# National discovery sources exposing public detail/proceeding URLs. The same
# cascade is also useful for long-tail TED downstream pages.
for portal in (
    'GENERIC_PUBLIC_PAGE','CA_CANADABUYS','QC_SEAO','DE_DOE','FR_BOAMP','NZ_GETS','AU_AUSTENDER',
    'US_SAM','US_SAM_BULK','NL_TENDERNED','NL_TENDERNED_RSS','PL_EZAMOWIENIA','PL_BZP','CH_SIMAP','LV_IUB',
):
    base.ADAPTERS[portal]=cascade_public_adapter
base.ADAPTERS['GR_KHMDHS']=adapter_greece

if __name__=='__main__':
    v2.main()
