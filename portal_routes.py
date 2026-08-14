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
    PortalRoute('TED', ('ted.europa.eu','docs.ted.europa.eu'), 'TED Search API -> notice links/eForms XML', 'extract BT-15 Documents URL; BT-615 if restricted', 'NONE for notice; downstream portal varies', 'buyer portal adapter from BT-15; official Search API supplies canonical XML/HTML/PDF URLs', 'AUTO_DISCOVERY_VALIDATED'),
    PortalRoute('EU_FUNDING_TENDERS', ('ec.europa.eu','commission.europa.eu'), 'TED BT-15 or Funding & Tenders procedure reference', 'Funding & Tenders procedure documents manifest/UI', 'MIXED_EULOGIN', 'public-page first pass then exact procedure route; persistent authenticated browser only when genuinely required', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('BE_EPROC', ('publicprocurement.be','eprocurement.gov.be'), 'TED BT-15 or Belgian e-Procurement search/reference', 'public procurement documents workspace', 'MIXED', 'public document-page extraction; persistent session only where the portal genuinely requires it', 'PUBLIC_PAGE_ADAPTER_LIVE_VALIDATED'),
    PortalRoute('UK_FTS', ('find-tender.service.gov.uk',), 'FTS notice/OCDS', 'extract document/communication links from notice/OCDS then route to eSender portal', 'NONE', 'ProContract/Atamis/Delta/Jaggaer/etc adapter', 'AUTO_DISCOVERY'),
    PortalRoute('UK_CONTRACTS_FINDER', ('contractsfinder.service.gov.uk',), 'official OCDS Search/Record/Release API', 'extract documents[].url and tender documents from OCDS/notice', 'NONE', 'follow buyer/eSender portal links', 'AUTO_DISCOVERY'),
    PortalRoute('SCOTLAND_PCS', ('publiccontractsscotland.gov.uk',), 'PCS public notice search', 'ASP.NET __doPostBack download-all current documents ZIP / individual document', 'NONE_WHEN_PUBLIC', 'record-interest/login state only when a specific notice gates documents', 'AUTO_DOWNLOAD_VALIDATED'),
    PortalRoute('PROCONTRACT', ('procontract.due-north.com',), 'public opportunity grid -> exact advertId', 'Advert page -> register interest -> attachments', 'LOGIN_REGISTER_INTEREST', 'public mirror hunt before auth; persistent storage_state after one manual login', 'AUTH_ROUTE_VALIDATED'),
    PortalRoute('LUX_PMP', ('pmp.b2g.etat.lu',), 'TED BT-15 / consultation id', 'anonymous DCE radio -> accept terms -> validate -> completeDownload', 'NONE', 'browser DOM adapter', 'AUTO_DOWNLOAD_VALIDATED'),
    PortalRoute('IRELAND_ETENDERS', ('etenders.gov.ie',), 'CfT Resource ID / advanced-search result', 'listContractDocuments -> anonymous popup -> Proceed without association -> downloadCftResourceItems', 'NONE_FOR_ANON_DOWNLOAD', 'logged-in association optional for update notifications, not required for public document ZIP', 'AUTO_DOWNLOAD_VALIDATED'),
    PortalRoute('FR_AWS', ('marches-publics.info','aws-achat.info'), 'notice/ref -> consultation page', 'anonymous/public DCE links when exposed; withdrawal form may be used by portal', 'CAPTCHA_SOMETIMES', 'public-page adapter first; buyer mirror/manual captcha only when actually challenged', 'PUBLIC_PAGE_ADAPTER_LIVE_VALIDATED'),
    PortalRoute('FR_ACHATPUBLIC', ('achatpublic.com',), 'notice/ref -> consultation id', 'consultation document withdrawal endpoint', 'MIXED', 'generic public-page first pass; browser/session adapter if required', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('FR_PLACE', ('marches-publics.gouv.fr',), 'PLACE consultation/reference', 'consultation DCE/technical annex download; large files may invoke PLACE download helper', 'MIXED', 'direct public annex links where exposed; browser/session fallback', 'ROUTE_IDENTIFIED'),
    PortalRoute('FR_MARCHES_SECUR', ('marches-securises.fr',), 'TED BT-15 / consultation page', 'public consultation/download links when exposed', 'MIXED', 'generic public-page first pass; add route-specific form adapter when unresolved', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('NL_TENDERNED', ('tenderned.nl',), 'TenderNed announcement platform / public XML notice API', 'publicly published tender documents on announcement detail; follow external platform when notice says procedure runs elsewhere', 'MIXED', 'generic public-page first pass; route external systems deterministically', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('DE_DTVP', ('dtvp.de',), 'TED BT-15 / DTVP procedure page', 'public procurement-document links from the procedure page', 'NONE_OR_MIXED_BY_NOTICE', 'public-page extraction; classify auth/CAPTCHA explicitly if present', 'PUBLIC_PAGE_ADAPTER_LIVE_VALIDATED'),
    PortalRoute('DE_EVERGABE', ('evergabe-online.de',), 'e-Vergabe tender id/reference', 'tenderdocuments.html?id=<id> and public procurement-document links when exposed', 'NONE_FOR_PUBLIC_DOCS', 'public-page extraction; participation activation only for bidding/updates', 'PUBLIC_PAGE_ADAPTER_LIVE_VALIDATED'),
    PortalRoute('DE_VERGABE_FAMILY', ('vergabe24.de','tender24.de','vergabe.metropoleruhr.de','meinauftrag.rib.de','vergabe.rlp.de','evergabe.nrw.de','deutsche-evergabe.de'), 'TED BT-15 / national procedure page', 'public page/document links; vendor-specific APIs/forms may exist', 'MIXED', 'generic public-page first pass; promote high-volume unresolved vendor families to dedicated adapters', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('ES_PLACSP', ('contrataciondelestado.es',), 'TED BT-15 / Spanish state procurement procedure', 'public pliegos/anexos/document links when exposed', 'MIXED', 'public-page extraction; preserve auth/no-file barrier separately', 'PUBLIC_PAGE_ADAPTER_LIVE_VALIDATED'),
    PortalRoute('ES_REGIONAL', ('contractaciopublica.cat','contratacion.euskadi.eus','juntadeandalucia.es','lajunta.es','hacienda.navarra.es'), 'TED BT-15 / regional contracting portal', 'public procedure/document links when exposed', 'MIXED', 'generic public-page first pass then regional route-specific adapter if unresolved', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('VORTAL', ('vortal.biz',), 'TED BT-15 / Vortal procedure', 'public procedure page where exposed; tender workspace may require session', 'MIXED', 'generic public-page first pass; auth route remains explicit', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('MERCELL', ('mercell.com','s2c.mercell.com'), 'notice -> tender id', 'tender workspace documents', 'LOGIN_OR_MIXED', 'generic public-page first pass; public mirror hunt then persistent authenticated storage_state only when genuinely required', 'AUTH_ROUTE_VALIDATED'),
    PortalRoute('PL_PUBLIC_PORTALS', ('platformazakupowa.pl','ezamowienia.gov.pl','ezamawiajacy.pl','eb2b.com.pl'), 'TED BT-15 / procedure URL', 'public documents when exposed by procedure page', 'MIXED', 'generic public-page first pass; dedicated vendor adapter for recurring unresolved domains', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('EE_RIIGIHANKED', ('riigihanked.riik.ee',), 'TED BT-15 / Estonian register procedure', 'public procedure/document links', 'MIXED', 'generic public-page first pass', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('SE_TENDSIGN', ('tendsign.com',), 'TED BT-15 / TendSign procedure', 'public procedure links; workspace rules vary', 'MIXED', 'generic public-page first pass; auth remains explicit', 'GENERIC_PUBLIC_PAGE_FIRST_PASS'),
    PortalRoute('QUEBEC_SEAO', ('seao.ca','donneesquebec.ca'), 'Données Québec weekly/monthly SEAO JSON -> SEAO notice', 'notice document package according to SEAO access rules', 'MIXED', 'open-data discovery first; buyer mirror search; authenticated browser if document package gated', 'AUTO_DISCOVERY'),
    PortalRoute('CLIRA', ('clira.io','clira.se'), 'notice/ref -> procurement page', 'procurement documents section', 'MIXED', 'public document URLs if exposed; otherwise persistent account session', 'ADAPTER_PENDING'),
    PortalRoute('CANADABUYS', ('canadabuys.canada.ca',), 'official tender-notice datasets + notice URL', 'notice attachments / source-system links', 'MIXED_BY_SOURCE', 'follow originating provincial/federal portal; alternate-source search; avoid relying on cloud-browser HTML when blocked', 'AUTO_DISCOVERY_ROUTE'),
    PortalRoute('SAM', ('sam.gov',), 'Contract Opportunities search/API/notice id', 'Attachments/Links; public attachments downloadable, controlled attachments classified separately', 'NONE_OR_CONTROLLED', 'controlled => AUTH/ACCESS_REQUIRED; public => direct/browser download', 'PUBLIC_VS_CONTROLLED_ROUTE'),
    PortalRoute('AUSTENDER', ('tenders.gov.au','help.tenders.gov.au'), 'ATM search/reference', 'ATM request documentation download', 'MIXED', 'browser/session adapter; buyer mirror fallback; classify cloud-IP blocks separately', 'ROUTE_IDENTIFIED'),
    PortalRoute('UNGM', ('ungm.org',), 'UNGM procurement notice id/search', 'DownloadDocument?documentId=...&noticeId=... / DownloadAllDocuments?noticeId=...', 'NONE_FOR_PUBLIC_NOTICE_DOCS', 'agency eSourcing may still require login for submission, independently of public DCE retrieval', 'AUTO_DOWNLOAD_VALIDATED'),
]

def route_for(url: str):
    low = (url or '').lower()
    for route in ROUTES:
        if any(d in low for d in route.domains):
            return route
    return None
