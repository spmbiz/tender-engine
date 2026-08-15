from __future__ import annotations

import json, os
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/FI_HILMA'));OUT.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc);PAGE=max(50,min(500,int(os.getenv('FI_PAGE_SIZE','250'))));MAX_PAGES=max(1,min(40,int(os.getenv('FI_MAX_PAGES','12'))))
BASE='https://www.hankintailmoitukset.fi';ENDPOINT=BASE+'/search/eformnotices'
S=requests.Session();S.headers.update({'User-Agent':'Tender-Engine/5.5 (+public procurement research)','Accept':'application/json,*/*'})
SELECT='noticeId,id,parentNoticeId,oldProcurementProjectId,procedureId,datePublished,dateModified,type,mainType,planId,titleFi,titleSv,titleEn,titleOther,organisationNameFi,organisationNameSv,organisationNameEn,organisationNameOther,organisationNationalRegistrationNumber,descriptionFi,descriptionSv,descriptionEn,descriptionOther,deadline,includesDynamicPurcharingSystem,isEuProcurement,isNationalProcurement,isNationalSmallValueProcurement,noticeNumber,isEForms,isPlan,expirationDate,procedureType,procurementTypeCode'

def clean(v):return ' '.join(str(v or '').split())
def pdt(v):
    s=clean(v)
    if not s:return None
    try:
        x=datetime.fromisoformat(s.replace('Z','+00:00'));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None

def pick(o,*keys):
    for k in keys:
        v=o.get(k)
        if v not in (None,''):return v
    return None

def main():
    rows=[];tele=[];seen=set();total_reported=None
    nowz=NOW.isoformat(timespec='milliseconds').replace('+00:00','Z')
    filt=f"(search.in(mainType, 'ContractNotices|NationalNotices', '|') and expirationDate ge {nowz})"
    for page in range(MAX_PAGES):
        params={'search':'*','queryType':'full','$top':PAGE,'$skip':page*PAGE,'searchMode':'all','$orderby':'datePublished desc','$count':'true','$filter':filt,'$select':SELECT}
        try:r=S.get(ENDPOINT,params=params,timeout=90);entry={'page':page,'url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type')};tele.append(entry);r.raise_for_status();data=r.json()
        except Exception as exc:tele.append({'page':page,'error':repr(exc)});break
        if isinstance(data,dict):
            total_reported=data.get('@odata.count') or data.get('count') or total_reported;arr=data.get('value') or data.get('results') or data.get('data') or []
        elif isinstance(data,list):arr=data
        else:arr=[]
        entry['items']=len(arr)
        if not arr:break
        for o in arr:
            if not isinstance(o,dict):continue
            rid=clean(pick(o,'noticeId','id','noticeNumber','procedureId'))
            if not rid:continue
            unique=clean(o.get('id') or rid)
            if unique in seen:continue
            seen.add(unique)
            title=clean(pick(o,'titleEn','titleFi','titleSv','titleOther'));buyer=clean(pick(o,'organisationNameEn','organisationNameFi','organisationNameSv','organisationNameOther'));desc=clean(pick(o,'descriptionEn','descriptionFi','descriptionSv','descriptionOther'))
            deadline=pdt(o.get('deadline'));expiration=pdt(o.get('expirationDate'));pub=pdt(o.get('datePublished'))
            procedure_id=clean(o.get('procedureId'));notice_id=clean(o.get('noticeId'));numeric_id=clean(o.get('id'));old_proc=clean(o.get('oldProcurementProjectId'))
            # The exact detail URL can vary between legacy and eForms; search fields remain canonical even if detail routing needs later refinement.
            detail=None
            if old_proc and numeric_id.isdigit():detail=f'{BASE}/en/public/procedure/{old_proc}/enotice/{numeric_id}'
            rows.append({'candidate_id':f'FI-HILMA:{notice_id or numeric_id or procedure_id}','source':'FI_HILMA','portal':'FI_HILMA','notice_id':notice_id or numeric_id,'procedure_id':procedure_id or None,'title':title or rid,'buyer':buyer or None,'deadline':deadline.isoformat() if deadline else None,'expiration':expiration.isoformat() if expiration else None,'published':pub.isoformat() if pub else None,'current':bool((deadline and deadline>=NOW) or (not deadline and expiration and expiration>=NOW)),'notice_url':detail,'description':desc,'procedure_type':o.get('procedureType'),'procurement_type_code':o.get('procurementTypeCode'),'is_eu_procurement':o.get('isEuProcurement'),'is_national_procurement':o.get('isNationalProcurement'),'is_small_value':o.get('isNationalSmallValueProcurement'),'route':{'document_urls':[],'detail_url':detail,'proceeding_url':detail,'hilma_search_id':numeric_id,'procedure_id':procedure_id},'discovered_at':NOW.isoformat()})
        if len(arr)<PAGE:break
    cur=[x for x in rows if x['current']]
    for fn,arr in (('raw.jsonl',rows),('current.jsonl',cur)):
        with (OUT/fn).open('w',encoding='utf-8') as f:
            for x in arr:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    stats={'source':'FI_HILMA','raw_materialized':len(rows),'current_materialized':len(cur),'deadline_parsed':sum(bool(x['deadline']) for x in rows),'published_parsed':sum(bool(x['published']) for x in rows),'buyer_parsed':sum(bool(x['buyer']) for x in rows),'national_notices':sum(bool(x.get('is_national_procurement')) for x in rows),'small_value_notices':sum(bool(x.get('is_small_value')) for x in rows),'eu_notices':sum(bool(x.get('is_eu_procurement')) for x in rows),'total_reported':total_reported,'generated_at':NOW.isoformat(),'errors':[] if rows else [{'type':'PUBLIC_JSON_SEARCH_EMPTY_OR_FAILED'}],'official_search':BASE+'/en/search','public_json_endpoint':ENDPOINT,'transport':'anonymous public HILMA JSON search endpoint observed from the official public SPA network; no subscription key/login required','telemetry':tele}
    (OUT/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(2)
if __name__=='__main__':main()
