# SPM Historical Opportunity Atlas v1

Scope: **historical structured evidence only**. No live tender, DCE, bid/no-bid, or current eligibility inference is used here.

The atlas combines the new ontology-free raw commercial miner with previously QA-clean historical lanes. `NOTICE_FIRST_TENDER` supports historical market/competition structure; `AWARD_FIRST_PROCUREMENT` supports demand, buyer and supplier structure but **does not prove open competition**. Currencies remain isolated.

## Reading the decisions

- `PROMOTE_ANALYSIS`: strong historical business lane; worth deeper archive decomposition.
- `INVESTIGATE_MODEL`: structurally attractive but delivery/panel/partner mechanics need historical research.
- `BROKER_CANDIDATE`: explicitly or naturally intermediary/reseller/fulfilment oriented.
- `HOLD_CONCENTRATION`: market exists but historical supplier concentration is unattractive.
- `HOLD_SPECIALIST`: market exists but appears regulated/specialist/heavy.

| # | Geography / lane | Grain | Historical evidence | Value | Supplier / competition evidence | SPM model hypothesis | Decision |
|---|---|---|---|---|---|---|---|
| 1 | Australia — ICT labour hire | AWARD_FIRST_PROCUREMENT | 667 records; 6 buyers; 4 repeat buyers | median AUD 619,413.96 | 169 suppliers; top share 4.5%; bidder evidence not authoritative for open-bid ease | source ICT contractors and take agency margin | **PROMOTE_ANALYSIS / STAFFING_BROKER** |
| 2 | Australia — contracted services | AWARD_FIRST_PROCUREMENT | 185 records; 4 buyers | median AUD 580,997.74 | 87 suppliers; top share 5.9% | decompose into recruitable / subcontractable service roles | **PROMOTE_ANALYSIS** |
| 3 | Australia — project management services (80161500) | AWARD_FIRST_PROCUREMENT | 69 records; 6 buyers; 3 repeat buyers | median AUD 775,678.83 | 41 suppliers; top share 11.6% | talent / consultant brokerage | **PROMOTE_ANALYSIS / STAFFING_BROKER** |
| 4 | Australia — temporary personnel services | AWARD_FIRST_PROCUREMENT | 68 records; 3 buyers; 2 repeat buyers | median AUD 752,444 | 47 suppliers; top share 7.4% | staffing agency / contractor placement | **PROMOTE_ANALYSIS / STAFFING_BROKER** |
| 5 | Australia — business analyst | AWARD_FIRST_PROCUREMENT | 14 records; 5 buyers; 4 repeat buyers | median AUD 647,741.60 | 12 suppliers; top share 14.3% | recruit individual analysts and retain spread | **PROMOTE_ANALYSIS / STAFFING_BROKER** |
| 6 | Australia — software support services | AWARD_FIRST_PROCUREMENT | 19 records; 4 buyers; 2 repeat buyers | median AUD 772,997.56 | 12 suppliers; top share 21.1% | subcontract support / reseller-managed service | **INVESTIGATE_MODEL** |
| 7 | Australia — software development services | AWARD_FIRST_PROCUREMENT | 5 records; 3 buyers | median AUD 2.30m | 5 suppliers; top share 20% | software delivery using subcontractors / AI leverage | **INVESTIGATE_MODEL** |
| 8 | Australia — data services | AWARD_FIRST_PROCUREMENT | 11 records; 2 buyers | median AUD 1.382m | 9 suppliers; top share 18.2% | data processing / analytics / migration if non-classified | **DECOMPOSE / PROMOTE_ANALYSIS** |
| 9 | Netherlands — Softwarebroker | NOTICE_FIRST_TENDER | 3 recurring notices; 3 municipal buyers | observed EUR 9m / 19.6m / 20m | bidder/supplier concentration UNKNOWN in current cohort | literal software-broker contract | **BROKER_CANDIDATE — HIGH INTEREST** |
| 10 | Finland — software & cloud licence resale (`Ohjelmisto- ja pilvipalvelulisenssien jälleenmyynti`) | NOTICE_FIRST_TENDER | 4 notices; 3 buyers; repeat buyer present | median EUR 26.5m; examples EUR 7m and 46m | current bidder/supplier concentration UNKNOWN | literal licence/cloud reseller | **BROKER_CANDIDATE — HIGH INTEREST** |
| 11 | Sweden — consultant broker (`Konsultmäklare`) | NOTICE_FIRST_TENDER | 3 notices; 3 buyers | SEK 400m / 517m / 1.15bn observed | current bidder/supplier concentration UNKNOWN | literal consultant marketplace/broker | **BROKER_CANDIDATE; SCALE RISK** |
| 12 | Portugal — Microsoft licences + connected services | NOTICE_FIRST_TENDER | 4 recurring notices; 2 buyers; repeat buyer | median EUR ~14.10m | bidder/supplier concentration UNKNOWN | Microsoft licensing reseller / integrator | **BROKER_CANDIDATE; PARTNER RISK** |
| 13 | Germany — official postal delivery of administrative notices | NOTICE_FIRST_TENDER | 3 notices; 2 buyers; repeat buyer; OPEN_PUBLIC | median observed ~EUR 12.03m | current supplier concentration UNKNOWN | postal fulfilment / routing intermediary | **INVESTIGATE_MODEL / FULFILMENT** |
| 14 | Finland — cleaning consumables (`Puhtaanapidon tarvikkeet`) | NOTICE_FIRST_TENDER | 3 recurring notices; 2 buyers; repeat buyer | examples EUR 3.608m and 26.199m | supplier concentration UNKNOWN | standardized-goods sourcing / brokerage | **BROKER_CANDIDATE / STANDARD GOODS** |
| 15 | Québec — commercial printing | NOTICE_FIRST_TENDER | 68 clean records; 36 buyers; 12 repeat buyers | median award CAD 129,800 | median bidders 2; fragmented winners; top historical winner ~10.2% | print broker / outsource production | **PROMOTE_ANALYSIS / BROKER** |
| 16 | Germany — website maintenance / hosting / support | NOTICE_FIRST_TENDER | 90 clean records; 34 buyers; 5 repeat buyers | median award EUR 419,100.32 | median bidders 3; top historical supplier ~8.33% | lean digital core / subcontract development | **PROMOTE_ANALYSIS / CORE** |
| 17 | France — graphic design / DTP | NOTICE_FIRST_TENDER | 194 clean records; 169 buyers; 21 repeat buyers | median award EUR 276,100 | top supplier share ~2.33%; bidder field often UNKNOWN | AI-assisted creative + human QA | **PROMOTE_ANALYSIS / CORE** |
| 18 | France — commercial print | NOTICE_FIRST_TENDER | 779 clean records; 594 buyers; 124 repeat buyers | median award EUR 341,666.67 | top supplier share ~1.43%; bidder field often UNKNOWN | print brokerage | **PROMOTE_ANALYSIS / BROKER** |
| 19 | France — written translation | NOTICE_FIRST_TENDER | 139 precision records; 117 buyers; 16 repeat buyers | median award EUR 220,000 | top supplier share ~3.03%; bidder field often UNKNOWN | translation subcontract network + AI assistance | **PROMOTE_ANALYSIS / CORE** |
| 20 | France — transcription | NOTICE_FIRST_TENDER | 58 precision records; 53 buyers; 5 repeat buyers | median award EUR 320,000 | top supplier share ~10% | AI transcription + human QA | **PROMOTE_ANALYSIS / CORE** |
| 21 | France — web maintenance | NOTICE_FIRST_TENDER | 121 precision records; 112 buyers; 8 repeat buyers | median award EUR 250,000 | top supplier share ~12.5% | lean web maintenance / subcontract | **PROMOTE_ANALYSIS / CORE** |
| 22 | France — web design / redesign | NOTICE_FIRST_TENDER | 66 precision records; 59 buyers; 7 repeat buyers | median award EUR 168,695 | top supplier share ~33.3% in current historical slice | AI/low-code + specialist subcontractors | **PROMOTE_ANALYSIS; WATCH CONCENTRATION** |
| 23 | Canada federal — written translation | NOTICE_FIRST_TENDER | 35 precision records; 26 buyers; 5 repeat buyers | median award CAD 326,214.28 | current top historical supplier share ~16.67% | translation network | **PROMOTE_ANALYSIS / CORE** |
| 24 | France — promotional merchandise | NOTICE_FIRST_TENDER | 107 precision records; 86 buyers | median award EUR 400,000 | broad supplier/reseller economics; current lane QA clean enough for brokerage watch | merchandise sourcing / white-label reseller | **BROKER_CANDIDATE** |
| 25 | France — mailing / routing | NOTICE_FIRST_TENDER | 200 precision records; 171 buyers | median award EUR 530,000 | pairs naturally with print; detailed bidder coverage incomplete | print-mail fulfilment broker | **BROKER_CANDIDATE / FULFILMENT** |
| 26 | USA — acquisition support services | AWARD_FIRST_PROCUREMENT | 78 awards; 49 buyers; 16 repeat buyers | median USD 906,228.66 | 47 suppliers; top share 23.1%; observed bidder count 1 is NOT open-bid evidence | procurement/admin specialists via contractor network | **PROMOTE_ANALYSIS / ADMIN-BPO** |
| 27 | USA — program management support services | AWARD_FIRST_PROCUREMENT | 31 awards; 14 buyers; 8 repeat buyers | median USD 3.277m | 21 suppliers; top share 19.4%; bidder=1 not interpreted as ease | contractor / consulting brokerage | **PROMOTE_ANALYSIS / STAFFING-BROKER** |
| 28 | USA — IT support services | AWARD_FIRST_PROCUREMENT | 18 awards; 13 buyers; 3 repeat buyers | median USD 4.705m | 16 suppliers; top share 16.7%; bidder=1 not interpreted as ease | managed IT/subcontract network | **INVESTIGATE_MODEL** |
| 29 | USA — professional support services | AWARD_FIRST_PROCUREMENT | 42 awards; 12 buyers; 8 repeat buyers | median USD 1.082m | 21 suppliers; top share 21.4%; bidder=1 not interpreted as ease | staffing / consulting / admin support | **DECOMPOSE / PROMOTE_ANALYSIS** |
| 30 | Australia — media buying services | AWARD_FIRST_PROCUREMENT | 11 awards; 5 buyers; 3 repeat buyers | median AUD 6.572m | **1 linked supplier; top share 100%** | media agency | **HOLD_CONCENTRATION** |

## Early strategic read

The archive is now surfacing three commercially distinct universes beyond the original web/design/print thesis:

1. **Explicit intermediary contracts** — `Softwarebroker`, software/cloud licence resale, `Konsultmäklare`, postal fulfilment. These deserve their own middleman/reseller atlas because the procurement object itself is intermediation.
2. **Human-capital brokerage** — Australia in particular shows unusually fragmented historical supplier structure for ICT labour hire, temporary personnel, business analysts, and project/program management.
3. **Administrative / support outsourcing** — USAspending shows broad buyer demand and fragmented suppliers for acquisition support, professional support, program-management support and IT support. This is award-first demand evidence, not proof of easy tender access.

## Important holds / anti-patterns

- A huge framework value is not attainable SPM revenue by itself.
- One historical bidder in USAspending is not evidence of an easy competitive tender.
- Health, construction, engineering, energy, defence-specific, insurance and regulated services can score highly on market structure while remaining poor SPM fits.
- Australia media buying is a concrete example where attractive values hide extreme historical supplier concentration.

## Next archive-only work

- expand explicit broker/reseller/intermediary wording over all Global Core rows;
- decompose Australia staffing into role families and buyer/supplier networks;
- decompose USA acquisition/professional/IT support into tasks that can actually be staffed/subcontracted;
- split standardized-goods procurement into brokerable product classes;
- add historical buyer recurrence and winner maps for every promoted row;
- grow this atlas from 30 to 50–100 semantically QA'd opportunities.
