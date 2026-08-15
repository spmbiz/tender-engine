from __future__ import annotations

import copy
import html
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
    priority=['CAPTCHA_REQUIRED','AUTH_REQUIRED','INTEREST_RECORDING_REQUIRED','ERROR_RETRYABLE','ROUTE_INCOMPLETE','NO_PUBLIC_FILE']
    final=next((s for s in priority if s in statuses),'GENERIC_PUBLIC_PAGE_UNRESOLVED')
    if final=='NO_PUBLIC_FILE':final='GENERIC_PUBLIC_PAGE_UNRESOLVED'
    manifest['status']=final


def adapter_ungm_guarded(candidate:dict,out:Path,manifest:dict):
    """Use public UNGM attachments when available, but surface interest-gated notices explicitly."""
    manifest.setdefault('dce_method_attempts',[])
    v2.optimized_ungm(candidate,out,manifest)
    if manifest.get('files'):
        manifest['dce_method_attempts'].append({'method':'UNGM_PUBLIC_ATTACHMENTS','outcome':'DOWNLOADED_PUBLIC','files':len(manifest.get('files') or [])})
        return
    route=candidate.get('route') or {}
    notice_id=str(route.get('notice_id') or candidate.get('notice_id') or '').strip()
    notice_url=candidate.get('notice_url') or (f'https://www.ungm.org/Public/Notice/{notice_id}' if notice_id else None)
    if not notice_url:
        manifest['status']='ROUTE_INCOMPLETE';return
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/5.0 public procurement research'})
    try:
        r=session.get(notice_url,timeout=45,allow_redirects=True)
        raw=html.unescape(r.text if r.ok else '')
        text=re.sub(r'<script\b[^>]*>.*?</script>',' ',raw,flags=re.I|re.S)
        text=re.sub(r'<style\b[^>]*>.*?</style>',' ',text,flags=re.I|re.S)
        text=re.sub(r'<[^>]+>',' ',text)
        text=re.sub(r'\s+',' ',html.unescape(text)).strip()
        if text:(out/'portal_page.txt').write_text(text[:500_000],encoding='utf-8')
        interest=bool(re.search(r'express interest|record(?:ing)? your interest|register interest',text,re.I))
        view_docs=bool(re.search(r'view documents|view document|e[- ]?sourcing portal',text,re.I))
        manifest['dce_method_attempts'].append({'method':'UNGM_ACCESS_STATE','url':notice_url,'http_status':r.status_code,'interest_signal':interest,'view_documents_signal':view_docs})
        if interest or view_docs:manifest['status']='INTEREST_RECORDING_REQUIRED'
        elif r.status_code in (401,403):manifest['status']='AUTH_REQUIRED'
        elif not r.ok:manifest['status']='ERROR_RETRYABLE'
        else:manifest['status']='NO_PUBLIC_FILE'
    except Exception as exc:
        manifest['status']='ERROR_RETRYABLE';manifest['error']=repr(exc)


def adapter_greece(candidate:dict,out:Path,manifest:dict):
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    cascade_public_adapter(candidate,out,manifest)


def _pl_document_nodes(obj):
    """Yield public eZamowienia document descriptors from GetTender JSON.

    Current GetTender records place the authoritative file metadata under
    tenderDocuments[].attachment while the downloadable public document id is
    the parent tenderDocuments[].objectId. Keep both ids because platform
    versions have used each of them in download routes.
    """
    if isinstance(obj,dict):
        low={str(k).lower():v for k,v in obj.items()}
        attachment=low.get('attachment') if isinstance(low.get('attachment'),dict) else None
        if attachment:
            alow={str(k).lower():v for k,v in attachment.items()}
            fname=alow.get('filename') or alow.get('file_name') or low.get('name')
            object_id=low.get('objectid') or low.get('documentid') or low.get('id')
            attachment_id=alow.get('uniqueattachmentidentifier') or alow.get('attachmentid') or alow.get('id')
            if fname and (object_id or attachment_id) and not alow.get('isdeleted'):
                yield {
                    'id':str(object_id or attachment_id),
                    'object_id':str(object_id) if object_id else None,
                    'attachment_id':str(attachment_id) if attachment_id else None,
                    'name':str(fname),
                    'mime_type':alow.get('mimetype'),
                    'size':alow.get('filesize'),
                }
        else:
            fname=next((low.get(k) for k in ('filename','file_name','documentname','originalfilename') if low.get(k)),None)
            did=next((low.get(k) for k in ('objectid','documentid','document_id','fileid','file_id','id') if low.get(k)),None)
            if fname and did:
                yield {'id':str(did),'object_id':str(did),'attachment_id':None,'name':str(fname),'mime_type':low.get('mimetype'),'size':low.get('filesize')}
        for v in obj.values():yield from _pl_document_nodes(v)
    elif isinstance(obj,list):
        for v in obj:yield from _pl_document_nodes(v)


def _pl_try_public_browser_download(tender_id:str,nodes:list[dict],out:Path,manifest:dict)->bool:
    """Click only publicly rendered tender-document links; never authenticates."""
    pw=browser=context=page=None;got=False
    try:
        pw,browser,context=v2.optimized_browser_context();page=context.new_page()
        proceeding=f'https://ezamowienia.gov.pl/mp-client/search/list/{tender_id}'
        page.goto(proceeding,wait_until='domcontentloaded',timeout=45000);page.wait_for_timeout(1200)
        for n in nodes[:80]:
            oid=n.get('object_id') or n.get('id')
            if not oid:continue
            url=f'https://ezamowienia.gov.pl/mp-client/search/tenderdocument/{tender_id}/{oid}'
            try:
                with page.expect_download(timeout=20000) as dl:
                    page.evaluate("u => { const a=document.createElement('a'); a.href=u; a.style.display='none'; document.body.appendChild(a); a.click(); a.remove(); }",url)
                rec=base.persist_download(out,dl.value,url);manifest['files'].append(rec);got=True
                manifest['dce_method_attempts'].append({'method':'PL_PUBLIC_BROWSER_DOCUMENT','url':url,'document_name':n.get('name'),'outcome':'DOWNLOADED'})
            except Exception as exc:
                manifest['dce_method_attempts'].append({'method':'PL_PUBLIC_BROWSER_DOCUMENT','url':url,'document_name':n.get('name'),'outcome':'NO_DOWNLOAD','error':repr(exc)[:300]})
        return got
    except Exception as exc:
        manifest['dce_method_attempts'].append({'method':'PL_PUBLIC_BROWSER_DOCUMENTS','error':repr(exc)[:500]});return got
    finally:
        try:
            if page:page.close()
        except Exception:pass
        try:
            if browser:browser.close()
        except Exception:pass
        try:
            if pw:pw.stop()
        except Exception:pass


def _pl_api_download(candidate:dict,out:Path,manifest:dict,session:requests.Session)->bool:
    route=candidate.get('route') or {};api=route.get('tender_api_url');tender_id=str(route.get('tender_id') or candidate.get('tender_id') or '').strip();template=route.get('document_download_template')
    if not api or not tender_id:return False
    try:
        r=session.get(api,timeout=60);manifest.setdefault('dce_method_attempts',[]).append({'method':'PL_GET_TENDER_API','url':api,'http_status':r.status_code,'bytes':len(r.content)})
        if not r.ok:return False
        data=r.json();nodes=[];seen=set()
        for n in _pl_document_nodes(data):
            key=(n.get('object_id'),n.get('attachment_id'),n.get('name'))
            if key not in seen:seen.add(key);nodes.append(n)
        manifest['pl_tender_document_descriptors']=nodes[:300]
        got=False
        for n in nodes[:120]:
            identifiers=[]
            for x in (n.get('object_id'),n.get('attachment_id'),n.get('id')):
                if x and x not in identifiers:identifiers.append(x)
            for did in identifiers:
                url=(template or f'https://ezamowienia.gov.pl/mp-readmodels/api/Tender/DownloadDocument/{tender_id}/{{document_id}}').replace('{document_id}',requests.utils.quote(str(did),safe=''))
                rec=base.direct_download(url,out,session)
                manifest['dce_method_attempts'].append({'method':'PL_DIRECT_DOCUMENT_API','url':url,'document_name':n['name'],'identifier':did,'outcome':'DOWNLOADED' if rec else 'NOT_FILE'})
                if rec:manifest['files'].append(rec);got=True;break
        if got:return True
        return _pl_try_public_browser_download(tender_id,nodes,out,manifest)
    except Exception as exc:
        manifest.setdefault('dce_method_attempts',[]).append({'method':'PL_GET_TENDER_API','url':api,'error':repr(exc)});return False


def adapter_poland(candidate:dict,out:Path,manifest:dict):
    manifest.setdefault('dce_method_attempts',[])
    if _attempt_direct(candidate,out,manifest):manifest['status']='DOWNLOADED_PUBLIC';return
    session=requests.Session();session.headers.update({'User-Agent':'Tender-Engine/5.1 public procurement research'})
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


# Generic national public-page adapters. These sources are already harvested as
# live candidates, so the DCE matrix must never drop them merely because the
# discovery lane was added after the original matrix allowlist.
for portal in (
    'GENERIC_PUBLIC_PAGE','CA_CANADABUYS','QC_SEAO','DE_DOE','FR_BOAMP',
    'NZ_GETS','AU_AUSTENDER','US_SAM','US_SAM_BULK','NL_TENDERNED',
    'NL_TENDERNED_RSS','CH_SIMAP','LV_IUB','NO_DOFFIN','FI_HILMA',
    'PT_BASE_OPEN','DK_UDBUD_PUBLIC','CZ_ZAKAZKY_GOV'
):
    base.ADAPTERS[portal]=cascade_public_adapter
for portal in ('PL_EZAMOWIENIA','PL_BZP'):base.ADAPTERS[portal]=adapter_poland
base.ADAPTERS['GR_KHMDHS']=adapter_greece
base.ADAPTERS['UNGM']=adapter_ungm_guarded

if __name__=='__main__':v2.main()