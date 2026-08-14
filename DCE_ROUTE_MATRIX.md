# DCE Route Matrix

This file is the operational routing map for procurement-document retrieval. `AUTO_DOWNLOAD_VALIDATED` means a GitHub Actions probe downloaded real procurement files end-to-end. `AUTH_ROUTE_VALIDATED` means the exact opportunity/document route is resolved but a legitimate authenticated supplier session is required. `CAPTCHA_ROUTE_VALIDATED` means the public route is known but automation must stop at the CAPTCHA. `ROUTE_IDENTIFIED`/`ADAPTER_PENDING` means the routing strategy is established but still needs a deterministic production adapter/probe.

| Portal family | Discovery route | DCE route | Gate | Operational status |
|---|---|---|---|---|
| TED | official Search API -> canonical XML/HTML/PDF links | eForms BT-15 / BT-615 -> downstream portal | none on notice | AUTO_DISCOVERY_VALIDATED |
| Luxembourg PMP | TED/consultation id | anonymous DCE -> accept terms -> validate -> completeDownload | none | AUTO_DOWNLOAD_VALIDATED |
| UNGM | public notice id | DownloadDocument / DownloadAllDocuments | none for public notice docs | AUTO_DOWNLOAD_VALIDATED |
| eTenders Ireland | CfT resourceId | listContractDocuments -> anonymous popup -> Proceed without association -> downloadCftResourceItems | none for public ZIP | AUTO_DOWNLOAD_VALIDATED |
| Public Contracts Scotland | public notice id | ASP.NET __doPostBack to download-all current documents ZIP | none when docs are public | AUTO_DOWNLOAD_VALIDATED |
| ProContract / Due North | public grid -> exact advertId | Advert -> register interest -> attachments | login + register interest | AUTH_ROUTE_VALIDATED |
| Mercell / S2C | notice -> tender id | tender workspace documents | login | AUTH_ROUTE_VALIDATED |
| AWS / marches-publics.info | notice/ref -> consultation | anonymous DCE withdrawal | CAPTCHA may appear | CAPTCHA_ROUTE_VALIDATED |
| Find a Tender | OCDS/notice | extract communication/document URL -> eSender adapter | downstream varies | AUTO_DISCOVERY |
| Contracts Finder | official OCDS Search/Record/Release | documents[].url / buyer portal | downstream varies | AUTO_DISCOVERY |
| EU Funding & Tenders | TED BT-15 / procedure ref | procedure document manifest/UI | mixed EU Login | ADAPTER_PENDING |
| Belgian e-Procurement | TED BT-15 / procurement ref | public documents workspace | mixed | ADAPTER_PENDING |
| Achatpublic | notice/ref -> consultation id | consultation document withdrawal | mixed | ADAPTER_PENDING |
| PLACE France | consultation/ref | DCE / technical annex download | mixed | ROUTE_IDENTIFIED |
| TenderNed | public announcement/XML | public docs or downstream platform | mixed | ROUTE_IDENTIFIED |
| e-Vergabe Germany | tender id/ref | tenderdocuments.html?id=... -> file/ZIP links when published | none for public docs | ROUTE_IDENTIFIED_NOT_YET_DOWNLOAD_VALIDATED |
| Quebec SEAO | Données Québec JSON -> SEAO notice | SEAO document package | mixed | AUTO_DISCOVERY |
| Clira | notice/ref -> procurement page | procurement documents section | mixed | ADAPTER_PENDING |
| CanadaBuys | official tender datasets -> notice/source system | attachments / source-system links | source-specific | AUTO_DISCOVERY_ROUTE |
| SAM.gov | opportunities API/search -> notice | Attachments/Links | public or controlled | PUBLIC_VS_CONTROLLED_ROUTE |
| AusTender | ATM search/ref | request documentation | mixed | ROUTE_IDENTIFIED |

## Mandatory resolver policy

1. Resolve the canonical notice/reference first; never guess a document URL.
2. Try public/direct DCE routes before login.
3. Before returning `AUTH_REQUIRED`, run exact-reference/title/buyer mirror search.
4. Do not bypass CAPTCHA, MFA, controlled-document access, or account restrictions.
5. Authenticated browser state must be stored only as encrypted CI secrets / external secret storage, never committed to this public repository.
6. Hash every downloaded file and re-check changed DCEs.
7. A tender cannot become FINAL SUPER GREEN until final mandatory gates are verified from the DCE or an equivalent authoritative source.
