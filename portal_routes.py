from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class PortalRoute:
    key: str
    domains: Tuple[str, ...]
    discovery: str
    document_route: str
    auth_mode: str
    fallback: str
    status: str

ROUTES = [
    PortalRoute('TED', ('ted.europa.eu','docs.ted.europa.eu'), 'TED Search/API -> eForms XML', 'extract BT-15 Documents URL; BT-615 if restricted', 'NONE for notice; downstream portal varies', 'buyer portal adapter from BT-15', 'AUTO_DISCOVERY'),
    PortalRoute('EU_FUNDING_TENDERS', ('ec.europa.eu','commission.europa.eu'), 'TED BT-15 or Funding & Tenders procedure reference', 'Funding & Tenders procedure documents manifest/UI', 'MIXED_EULOGIN', 'search exact procedure ref + buyer page; persistent authenticated browser when required', 'ADAPTER_REQUIRED'),
    PortalRoute('BE_EPROC', ('publicprocurement.be','eprocurement.gov.be'), 'TED BT-15 or Belgian e-Procurement search/reference', 'public procurement documents workspace', 'MIXED', 'TED/buyer mirror + persistent session only where portal requires it', 'ADAPTER_REQUIRED'),
    PortalRoute('UK_FTS', ('find-tender.service.gov.uk',), 'FTS notice/OCDS', 'extract document/communication links from notice/OCDS then route to eSender portal', 'NONE', 'ProContract/Atamis/Delta/etc adapter', 'AUTO_DISCOVERY'),
    PortalRoute('UK_CONTRACTS_FINDER', ('contractsfinder.service.gov.uk',), 'official OCDS Search/Record/Release API', 'extract documents[].url and tender documents from OCDS/notice', 'NONE', 'follow buyer/eSender portal links', 'AUTO_DISCOVERY'),
    PortalRoute('SCOTLAND_PCS', ('publiccontractsscotland.gov.uk',), 'PCS public notice search', 'notice attachments / buyer portal links', 'MIXED', 'browser adapter + authenticated state where attachment access requires account', 'ADAPTER_REQUIRED'),
    PortalRoute('PROCONTRACT', ('procontract.due-north.com',), 'public opportunity grid -> exact advertId', 'Advert page -> register interest -> attachments', 'LOGIN_REGISTER_INTEREST', 'public mirror hunt before auth; persistent storage_state after one manual login', 'AUTH_ROUTE_VALIDATED'),
    PortalRoute('LUX_PMP', ('pmp.b2g.etat.lu',), 'TED BT-15 / consultation id', 'anonymous DCE radio -> accept terms -> validate -> completeDownload', 'NONE', 'browser DOM adapter', 'AUTO_DOWNLOAD_VALIDATED'),
    PortalRoute('IRELAND_ETENDERS', ('etenders.gov.ie',), 'CfT Resource ID / advanced-search result', 'prepareViewCfTWS.do?resourceId=... -> contract documents endpoint', 'MIXED', 'browser adapter; login state if individual workspace restricts files', 'ROUTE_IDENTIFIED'),
    PortalRoute('FR_AWS', ('marches-publics.info','aws-achat.info'), 'notice/ref -> consultation page', 'anonymous DCE withdrawal form/document endpoint', 'CAPTCHA_SOMETIMES', 'buyer mirror search; manual captcha if challenged', 'CAPTCHA_ROUTE_VALIDATED'),
    PortalRoute('FR_ACHATPUBLIC', ('achatpublic.com',), 'notice/ref -> consultation id', 'consultation document withdrawal endpoint', 'MIXED', 'browser/session adapter; exact-ref mirror hunt', 'ADAPTER_REQUIRED'),
    PortalRoute('MERCELL', ('mercell.com','s2c.mercell.com'), 'notice -> tender id', 'tender workspace documents', 'LOGIN', 'public mirror hunt then persistent authenticated storage_state', 'AUTH_ROUTE_VALIDATED'),
    PortalRoute('CLIRA', ('clira.io','clira.se'), 'notice/ref -> procurement page', 'procurement documents section', 'MIXED', 'public document URLs if exposed; otherwise persistent account session', 'ADAPTER_REQUIRED'),
    PortalRoute('CANADABUYS', ('canadabuys.canada.ca',), 'official tender-notice datasets + notice URL', 'notice attachments / source-system links', 'MIXED_BY_SOURCE', 'follow originating provincial/federal portal; alternate-source search', 'AUTO_DISCOVERY'),
    PortalRoute('SAM', ('sam.gov',), 'Contract Opportunities search/API/notice id', 'Attachments/Links; public attachments downloadable, controlled attachments classified separately', 'NONE_OR_CONTROLLED', 'controlled => AUTH/ACCESS_REQUIRED; public => direct/browser download', 'PUBLIC_ATTACHMENTS_ROUTE'),
    PortalRoute('AUSTENDER', ('tenders.gov.au','help.tenders.gov.au'), 'ATM search/reference', 'ATM request documentation download', 'MIXED', 'browser/session adapter; buyer mirror fallback', 'ROUTE_IDENTIFIED'),
    PortalRoute('UNGM', ('ungm.org',), 'UNGM procurement notice id/search', 'notice documents / agency eTendering redirect', 'MIXED_BY_AGENCY', 'route to agency portal; authenticated session only when agency requires it', 'ROUTER_REQUIRED'),
]

def route_for(url: str):
    low = (url or '').lower()
    for route in ROUTES:
        if any(d in low for d in route.domains):
            return route
    return None
