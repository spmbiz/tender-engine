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
    PortalRoute('SCOTLAND_PCS', ('publiccontractsscotland.gov.uk',), 'PCS public notice search', 'notice current documents / download-all ZIP when publicly exposed', 'MIXED', 'record-interest/login state only when specific notice requires it', 'PUBLIC_DOCS_ROUTE_IDENTIFIED'),
    PortalRoute('PROCONTRACT', ('procontract.due-north.com',), 'public opportunity grid -> exact advertId', 'Advert page -> register interest -> attachments', 'LOGIN_REGISTER_INTEREST', 'public mirror hunt before auth; persistent storage_state after one manual login', 'AUTH_ROUTE_VALIDATED'),
    PortalRoute('LUX_PMP', ('pmp.b2g.etat.lu',), 'TED BT-15 / consultation id', 'anonymous DCE radio -> accept terms -> validate -> completeDownload', 'NONE', 'browser DOM adapter', 'AUTO_DOWNLOAD_VALIDATED'),
    PortalRoute('IRELAND_ETENDERS', ('etenders.gov.ie',), 'CfT Resource ID / advanced-search result', 'prepareViewCfTWS.do?resourceId=... -> listContractDocuments.do?resourceId=...', 'MIXED', 'browser adapter; login state if individual workspace restricts files', 'ROUTE_IDENTIFIED'),
    PortalRoute('FR_AWS', ('marches-publics.info','aws-achat.info'), 'notice/ref -> consultation page', 'anonymous DCE withdrawal form/document endpoint', 'CAPTCHA_SOMETIMES', 'buyer mirror search; manual captcha if challenged', 'CAPTCHA_ROUTE_VALIDATED'),
    PortalRoute('FR_ACHATPUBLIC', ('achatpublic.com',), 'notice/ref -> consultation id', 'consultation document withdrawal endpoint', 'MIXED', 'browser/session adapter; exact-ref mirror hunt', 'ADAPTER_REQUIRED'),
    PortalRoute('FR_PLACE', ('marches-publics.gouv.fr',), 'PLACE consultation/reference', 'consultation DCE/technical annex download; large files may invoke PLACE download helper', 'MIXED', 'direct public annex links where exposed; browser/session fallback', 'ROUTE_IDENTIFIED'),
    PortalRoute('NL_TENDERNED', ('tenderned.nl',), 'TenderNed announcement platform / public XML notice API', 'publicly published tender documents on announcement detail; follow external platform when notice says procedure runs elsewhere', 'MIXED', 'TenderNed public notice API credentials for XML; browser public document download; route external systems', 'ROUTE_IDENTIFIED'),
    PortalRoute('DE_EVERGABE', ('evergabe-online.de',), 'e-Vergabe tender id/reference', 'tenderdocuments.html?id=<id> -> free individual/ZIP procurement-document downloads', 'NONE_FOR_FIRST_VIEW', 'participation activation only for bidding/updates', 'PUBLIC_DOCS_ROUTE_IDENTIFIED'),
    PortalRoute('QUEBEC_SEAO', ('seao.ca','donneesquebec.ca'), 'Données Québec weekly/monthly SEAO JSON (open calls included) -> SEAO notice', 'notice document package according to SEAO access rules', 'MIXED', 'open-data discovery first; buyer mirror search; authenticated browser if document package gated', 'AUTO_DISCOVERY'),
    PortalRoute('MERCELL', ('mercell.com','s2c.mercell.com'), 'notice -> tender id', 'tender workspace documents', 'LOGIN', 'public mirror hunt then persistent authenticated storage_state', 'AUTH_ROUTE_VALIDATED'),
    PortalRoute('CLIRA', ('clira.io','clira.se'), 'notice/ref -> procurement page', 'procurement documents section', 'MIXED', 'public document URLs if exposed; otherwise persistent account session', 'ADAPTER_REQUIRED'),
    PortalRoute('CANADABUYS', ('canadabuys.canada.ca',), 'official tender-notice datasets + notice URL', 'notice attachments / source-system links', 'MIXED_BY_SOURCE', 'follow originating provincial/federal portal; alternate-source search', 'AUTO_DISCOVERY'),
    PortalRoute('SAM', ('sam.gov',), 'Contract Opportunities search/API/notice id', 'Attachments/Links; public attachments downloadable, controlled attachments classified separately', 'NONE_OR_CONTROLLED', 'controlled => AUTH/ACCESS_REQUIRED; public => direct/browser download', 'PUBLIC_ATTACHMENTS_ROUTE'),
    PortalRoute('AUSTENDER', ('tenders.gov.au','help.tenders.gov.au'), 'ATM search/reference', 'ATM request documentation download', 'MIXED', 'browser/session adapter; buyer mirror fallback', 'ROUTE_IDENTIFIED'),
    PortalRoute('UNGM', ('ungm.org',), 'UNGM procurement notice id/search', 'public notice document links; DownloadDocument?documentId=...&noticeId=... and DownloadAllDocuments?noticeId=...', 'MIXED_BY_AGENCY', 'full eSourcing/submission may require agency login even when public docs download', 'PUBLIC_DOCS_ROUTE_IDENTIFIED'),
]

def route_for(url: str):
    low = (url or '').lower()
    for route in ROUTES:
        if any(d in low for d in route.domains):
            return route
    return None
