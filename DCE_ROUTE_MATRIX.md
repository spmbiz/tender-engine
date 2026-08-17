# DCE Route Matrix

This file is the operational routing map for procurement-document retrieval. `AUTO_DOWNLOAD_VALIDATED` means a GitHub Actions probe downloaded real procurement files end-to-end. `AUTH_ROUTE_VALIDATED` means the exact opportunity/document route is resolved but a legitimate authenticated supplier session is required. `CAPTCHA_ROUTE_VALIDATED` means the public route is known but automation must stop at the CAPTCHA. `ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION` means production code and a live smoke route exist, but an end-to-end GitHub Actions download has not yet been confirmed. `BARRIER_CLASSIFIER_ACTIVE` means the public route is attempted first and a legitimate auth/interest gate is preserved rather than bypassed.

| Portal family | Discovery route | DCE route | Gate | Operational status |
|---|---|---|---|---|
| TED | official Search API -> canonical XML/HTML/PDF links | eForms BT-15 / BT-615 -> named downstream portal family | none on notice | AUTO_DISCOVERY_VALIDATED + V14_DOWNSTREAM_ROUTING_ACTIVE |
| Luxembourg PMP | TED/consultation id | anonymous DCE -> accept terms -> validate -> completeDownload | none | AUTO_DOWNLOAD_VALIDATED |
| UNGM | public notice id | DownloadDocument / DownloadAllDocuments | none for public notice docs | AUTO_DOWNLOAD_VALIDATED |
| eTenders Ireland | CfT resourceId | listContractDocuments -> anonymous popup -> Proceed without association -> downloadCftResourceItems | none for public ZIP | AUTO_DOWNLOAD_VALIDATED |
| Public Contracts Scotland | public notice id | ASP.NET __doPostBack to download-all current documents ZIP | none when docs are public | AUTO_DOWNLOAD_VALIDATED |
| ProContract / Due North | public grid / eSender URL -> exact advert | public files first; register-interest boundary preserved | login + register interest where required | AUTH_ROUTE_VALIDATED + BARRIER_CLASSIFIER_ACTIVE |
| Mercell / S2C | TED/downstream URL -> named Mercell family | public SPA/network/file probe before gate | commonly login | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| AWS / marches-publics.info | notice/ref -> consultation | anonymous DCE withdrawal | CAPTCHA may appear | CAPTCHA_ROUTE_VALIDATED |
| Find a Tender | OCDS/notice | communication/document URL -> runtime eSender family router | downstream varies | ESENDER_ROUTER_ACTIVE |
| Contracts Finder | official OCDS Search/Record/Release | direct documents first -> buyer/eSender runtime router | downstream varies | ESENDER_ROUTER_ACTIVE |
| EU Funding & Tenders | TED BT-15 / procedure ref | public procedure/document SPA + network/file discovery | mixed EU Login | ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| Belgian e-Procurement | TED BT-15 / procurement ref | public publication-workspace documents page | mixed | ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| Achatpublic | notice/ref -> consultation id | public consultation document controls/network | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| PLACE France | consultation/ref | DCE / technical annex download | mixed | ROUTE_IDENTIFIED |
| TenderNed | public announcement/XML | public Documents tab / file controls / downstream platform | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| e-Vergabe NRW | tender id/ref | public `/documents` page -> individual files / ZIP controls | none for published public docs | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| e-Vergabe Germany vendor family | tender id/ref | public document page / file controls | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| Slovakia UVO | TED/national detail id | deterministic official `/dokumenty/{procedure_id}` public documents route | none when unrestricted | DETERMINISTIC_ROUTE_ADAPTER_ACTIVE |
| Hungary EKR | procedure id | Közbeszerzési dokumentáció -> select public document checkboxes -> download selected documents | mixed | DEDICATED_PUBLIC_DOCUMENT_UI_ACTIVE |
| Bulgaria CAIS EOP | notice/procedure | public attachment/file controls + export package when published | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| Catalonia Contractació Pública | publication id | public Documentació / PCAP / PPT file controls | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| Poland eZamowienia | national API/procedure | public GetTender metadata -> DownloadDocument/browser fallback | mixed | DEDICATED_PUBLIC_DOCUMENT_ADAPTER_ACTIVE |
| PlatformaZakupowa | downstream transaction URL | public page/file probe; classify OpenNexus OAuth boundary when redirected | mixed / SSO on some procedures | NAMED_ADAPTER + AUTH_BOUNDARY_ACTIVE |
| Portugal acinGov | public procedure URL | anonymous public probe then procedure-access gate | login/registration on gated procedures | AUTH_BOUNDARY_CLASSIFIER_ACTIVE |
| e-Avrop Sweden | procurement page | public probe; preserve Hämta & Bevaka interest/watch boundary | interest/watch required on affected notices | INTEREST_BOUNDARY_CLASSIFIER_ACTIVE |
| Clira | notice/ref -> procurement page | named procurement documents SPA/network route | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| CanadaBuys | official tender datasets -> tender notice | first-party `/sites/default/files/webform/tender_notice/` attachments -> direct download | none for published CanadaBuys attachments | DETERMINISTIC_PUBLIC_ATTACHMENT_ADAPTER_ACTIVE |
| Quebec SEAO | Données Québec JSON -> SEAO notice | SEAO document package | mixed | AUTO_DISCOVERY; DEDICATED_DCE_PENDING |
| SAM.gov | opportunities API/search -> notice | public v3 Attachments/Links; controlled files remain controlled | public or controlled | PUBLIC_VS_CONTROLLED_ROUTE |
| AusTender | ATM search/ref | request documentation | mixed | ROUTE_IDENTIFIED; DEDICATED_DCE_PENDING |
| UK Atamis | public Salesforce/ProSpend opportunity URL | public Documentation first; preserve Register Interest/login boundary | mixed / register interest | BARRIER_CLASSIFIER_ACTIVE |
| UK Delta eSourcing | eSender opportunity URL | public page first -> Delta response/document boundary | login/registration on gated ITTs | BARRIER_CLASSIFIER_ACTIVE |
| UK In-Tend | tenant opportunity URL | public page first -> tender-document access boundary | registration/login where required | BARRIER_CLASSIFIER_ACTIVE |
| UK JAGGAER / BravoSolution | tenant opportunity URL | public page first -> secure tender-document access boundary | registration/login where required | BARRIER_CLASSIFIER_ACTIVE |
| EU Supply | public purchase URL | named public purchase/document SPA/network route | mixed | NAMED_ADAPTER_ACTIVE_PENDING_LIVE_VALIDATION |
| New Zealand GETS / TenderLink | GETS notice -> downstream TenderLink when specified | public GETS probe; preserve TenderLink registration boundary | registration on affected RFX documents | BARRIER_CLASSIFIER_ACTIVE |

## V14 expansion coverage

The V14 resolver promotes the previous generic backlog into explicit host/vendor families across EU Funding & Tenders, Belgian e-Procurement, Mercell, Vortal, EU Supply, Sweden, Norway, Bulgaria, Romania, Hungary, Croatia, Slovakia, Latvia, Czechia, Greece, France, Spain, Italy, Portugal, Austria, Germany, Poland, Netherlands, Switzerland, Estonia, UK eSenders, New Zealand TenderLink, and CanadaBuys. The generic fallback remains available for unknown public pages; named routes are preferred so unresolved volume can be measured by vendor family instead of disappearing into one bucket.

## Mandatory resolver policy

1. Resolve the canonical notice/reference first; never guess a document URL.
2. Try public/direct DCE routes before login.
3. Before returning `AUTH_REQUIRED`, run the exact-reference/title/buyer mirror strategy where available.
4. Do not bypass CAPTCHA, MFA, controlled-document access, registration, or record-interest requirements.
5. Authenticated browser state must be stored only as encrypted CI secrets / external secret storage, never committed to this public repository.
6. Hash every downloaded file and re-check changed DCEs.
7. A tender cannot become FINAL SUPER GREEN until final mandatory gates are verified from the DCE or an equivalent authoritative source.
8. Adapter existence is not download validation: keep live-smoke / end-to-end validation state separate from route support.
