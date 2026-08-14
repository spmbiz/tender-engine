import json
from portal_routes import ROUTES, route_for

SAMPLES = {
 'TED':'https://ted.europa.eu/en/notice/-/detail/561068-2026',
 'EU_FUNDING_TENDERS':'https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home',
 'BE_EPROC':'https://www.publicprocurement.be/',
 'UK_FTS':'https://www.find-tender.service.gov.uk/',
 'UK_CONTRACTS_FINDER':'https://www.contractsfinder.service.gov.uk/',
 'SCOTLAND_PCS':'https://www.publiccontractsscotland.gov.uk/',
 'PROCONTRACT':'https://procontract.due-north.com/Advert?advertId=b476ca84-8695-f111-813c-005056b64545',
 'LUX_PMP':'https://pmp.b2g.etat.lu/',
 'IRELAND_ETENDERS':'https://www.etenders.gov.ie/epps/home.do',
 'FR_AWS':'https://www.marches-publics.info/',
 'FR_ACHATPUBLIC':'https://www.achatpublic.com/',
 'MERCELL':'https://s2c.mercell.com/',
 'CLIRA':'https://clira.io/',
 'CANADABUYS':'https://canadabuys.canada.ca/en/tender-opportunities',
 'SAM':'https://sam.gov/content/opportunities',
 'AUSTENDER':'https://www.tenders.gov.au/',
 'UNGM':'https://www.ungm.org/Public/Notice',
}

rows=[]
for r in ROUTES:
    sample=SAMPLES.get(r.key,'')
    match=route_for(sample)
    rows.append({
      'key':r.key,
      'sample':sample,
      'routing_ok':bool(match and match.key==r.key),
      'discovery':r.discovery,
      'document_route':r.document_route,
      'auth_mode':r.auth_mode,
      'fallback':r.fallback,
      'status':r.status,
    })
print(json.dumps(rows,indent=2,ensure_ascii=False))
assert all(x['routing_ok'] for x in rows)
