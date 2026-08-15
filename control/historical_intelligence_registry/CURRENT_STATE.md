# Historical Intelligence — Current State

Updated: 2026-08-16 (Europe/Brussels project session)

## Scope firewall

**Historical archive analysis only.** Live tenders, DCE retrieval and final bid/no-bid are explicitly outside this state.

## Canonical corpus authority

`control/historical_commercial_miner_v1/MASTER_SUMMARY.json`

- procurement records scanned: **18,271,075**
- award rows scanned: **20,307,312**
- award↔supplier links scanned: **19,958,186**
- Global Core v4: **2,250,547 notice-first**
- USAspending: **15,842,317 award-first**
- AusTender: **178,211 award-first**

## No-loss / provenance rules

Hard rule: **REJECTED_CLASSIFICATION ≠ REJECTED_RECORD.**

- Source records are never deleted because a regex, ontology or GPT hypothesis was wrong.
- Wrong mappings return to reclassification/open-world queues.
- FACTS, semantic classifications, model hypotheses and strategic verdicts are separate layers.
- Superseded interpretations remain in Git history / versioned ledgers and are named explicitly.
- Parallel derived workers now publish to isolated releases before any master consolidation; concurrent writers no longer share a clobbering release.

Current strategic ledgers:
- `OPEN_WORLD_DECISIONS_2026-08-16.jsonl`
- `ASYMMETRY_DECISIONS_V3_2026-08-16.jsonl`
- `ASYMMETRIC_PRIORITY_V3.md`

## Global information-work — current authority v3.1

Authority: `control/historical_information_work_pure_core_v3_1/`

Global Core records scanned: **2,250,547**.
Strict title-led information-work matches: **253**.
After semantic hardening, **110** are routed as pure digital/remote service rather than platform, physical-input, specialist or collision classes.

Pure core:
- **Evidence/literature synthesis: 29** · 22 buyers · 7 countries · observed median bidders 1
- **Data entry/keying: 18** · 17 buyers · 6 countries · bidders 2
- **Data collection/research: 17** · 16 buyers · 8 countries · bidders 2
- **Content/data migration: 11** · 8 buyers · 5 countries · bidders 1
- **Data validation/coding: 11** · 7 buyers · 4 countries · bidders 3.5
- **Data cleaning/enrichment/MDM: 7** · 6 buyers · 6 countries · bidders 1
- **Database/registry operations: 7** · 2 buyers · 2 countries
- OCR/text extraction: 3
- Desk research/benchmarking: 2
- metadata, annotation, redaction, knowledge-content and document conversion: small precision signals

v3.1 explicitly removes from the pure core:
- physical document digitization/intake;
- inspection/inventory plus data entry;
- OCR software/license procurement;
- MDM/platform implementations;
- large embedded IT migrations;
- domain-specialist evidence reviews;
- semantic substring collisions such as `registre` inside French `enregistrement`.

**Strategic verdict:** Data entry and evidence synthesis are Tier A asymmetric theses; data collection and validation are A- conditional; pure migration is B+; tiny n=1–3 families are signals, not market-size claims.

## USA network / agency economics — current authority v3.2

Authority: `control/historical_usa_network_intermediary_v3_2/`
QA: `control/historical_usa_network_qa_v3_2/`

USAspending records scanned: **15,842,317**.
Strict title-led network-service awards: **12,267**.

- **Expert witness:** 7,674 awards · 182 buyers · 2,088 suppliers · median USD26.4k · 138 suppliers serve ≥3 buyers · repeat-org/network award share 40.4% → **NETWORK PLAUSIBLE / HOLD ECONOMICS**.
- **Court reporting:** 3,003 · 191 buyers · 219 suppliers · median USD2.4k · 47 suppliers serve ≥3 buyers · repeat-org/network share **78.5%** → **PROMOTE NETWORK MODEL**.
- **General language interpretation:** 928 · 268 buyers · 216 suppliers · median USD12.9k · repeat-org/network share **61.9%** → **PROMOTE CONDITIONALLY NETWORK**.
- **Sign-language interpretation:** 330 · 126 buyers · 82 suppliers · repeat-org/network share **79.4%** → **PROMOTE NETWORK MODEL**.
- Litigation support: 298 · 63 buyers · 89 suppliers; high median but concentration/complexity → hold economics.
- Remote-language interpretation explicit-title subset: 34; too small for independent market-size conclusion.

QA confirms multi-buyer agency-like court-reporting suppliers (e.g. VET Reporting, Gradillas, Capital Reporting, Anderson Court Reporting) and a real organizational interpretation market. Historical evidence does **not** prove current certification, set-aside or contract-vehicle access.

## Australia review/evaluation — current authority v3.2

Authority: `control/historical_australia_review_evaluation_v3_2/`
QA: `control/historical_australia_review_qa_v3_2/`

AusTender records scanned: **178,211**.
Strict semantic review/evaluation rows: **1,121**.

v3.2 supersedes the earlier broad `PROGRAM_EVALUATION` aggregate after QA found Defence **Test and Evaluation Services** contamination.

Current split:
- **Project/program assurance:** 607 remote-analytical-plausible · 19 buyers · 115 suppliers · median AUD17.65k · top supplier5.9% → real market, but **PARTNER/HOLD** because assurance panels/seniority/credentials may dominate.
- **Generic evaluation unresolved:** 168 · 31 buyers · 115 suppliers · median AUD94.7k → **HOLD**, no forced interpretation.
- **Policy/program evaluation:** 113 remote-analytical · 22 buyers · 64 suppliers · median **AUD238.8k** · top12.4% plus 2 specialist rows → **PROMOTE CONDITIONALLY NETWORK+PARTNER**.
- **Independent review:** 91 · 38 buyers · 80 suppliers · median **AUD68.9k** · top4.4% → **PROMOTE CONDITIONALLY NETWORK+PARTNER**.
- Research/monitoring/evaluation: 72 remote +1 human-heavy · 25 buyers · 41 suppliers · median AUD197.5k → conditional.
- **Technical Test & Evaluation:** 67 · 2 buyers · 46 suppliers · median AUD510.5k → **HARD / RECLASSIFIED**, not evidence for lean program evaluation.

QA examples for policy/program evaluation are real government-program evaluations in health, social policy, drought, mental health and related programs. Independent-review samples are overwhelmingly report/review/analysis deliverables but span many domains, so expert partnering remains important.

## Australia recruitment / digital learning — prior strong expansions retained

Authority: `control/historical_australia_asymmetric_services_v2/` plus description-backed QA.

- General recruitment/search: **2,130 awards · 94 buyers · ~359 normalized supplier keys · top normalized6.6%** → **Tier A network/automation thesis**.
- Executive search: 118 · 40 buyers · ~46 normalized keys → high, more relationship-heavy.
- Digital/e-learning/platform/content: 92 · 51 buyers · ~56 normalized keys → high conditional.
- Training design/content broad bucket remains held because delivery models mix.

## Open-world expansion — current native-code/economic authority v4

Discovery authority: `control/historical_open_world_next_wave_v3/`
Economic routing: `control/historical_open_world_economic_archetypes_v4/`
Broker QA: `control/historical_open_world_broker_qa_v4/`

A mechanism-regex scan of an additional **3,500** unknown clusters recognized only 3 cluster×mechanism pairs; **3,497 remained untagged**, proving that more keyword ontologies are not enough.

The next layer therefore classified the top **1,000** untagged clusters by native code/economic archetype:
- 55 broker/resell candidates
- 51 local-network candidates
- 77 core/partner-service candidates
- 5 complex broker hypotheses
- 93 hard/regulated
- 719 open review

Broker QA on the 55 candidates:
- 16 office/IT equipment clusters
- 9 food supply
- 8 lab reagents/consumables
- 11 furniture clusters including one supply/install cluster
- 7 telecom/electrical clusters
- 2 office-stationery
- 2 sport/recreation equipment

Most promising new broker test: **office consumables / toner / selected IT equipment**, but only fragmented cohorts. Examples include:
- a 24-record /15-buyer /10-supplier office-consumable cohort with median 5 bidders;
- a 16-record /12-buyer /8-supplier toner/print-consumables cohort with top supplier share23%;
- other toner/IT clusters are heavily concentrated and should be avoided.

Food supply is held for logistics/perishability/margin friction. Lab reagents are held for compatibility/regulatory friction. Furniture is medium-friction due installation/logistics.

## Current SPM asymmetric archetypes

The project should discover and rank by **economic mechanism**, not only named sectors:

1. **Information in → structured output out** — data entry, validation, synthesis, research, selected migration/cleaning.
2. **Demand in → right human out** — recruitment, court reporters, interpreters, reviewers, specialist networks.
3. **Specification in → sourced SKU out** — toner/office/IT consumables, print, promo goods, standardized supply.
4. **Buyer need in → orchestrated specialist deliverable out** — independent reviews, policy evaluations, selected assurance/expert work.

This framing is the current strategic authority because it can surface businesses that were not present in the original ontology.

## Highest priority now

### Tier A
- data entry / capture / keying — CORE
- evidence / literature synthesis — CORE + specialist QA where required
- court-reporting agency — NETWORK
- sign-language interpretation — NETWORK
- recruitment/search — NETWORK + automation
- general language interpretation — NETWORK conditional
- digital/e-learning — CORE/PARTNER/RESELL conditional

### Tier A-
- Australia independent review — NETWORK+PARTNER
- Australia policy/program evaluation — NETWORK+PARTNER
- data collection/research orchestration — CORE/NETWORK
- data validation/coding — CORE
- translation/transcription/DTP/accessibility — existing core historical lanes
- web maintenance/redesign — existing core historical lanes

### Tier B+
- toner / office-consumables resale — BROKER, dedicated margin test required
- pure data/content migration — CORE/PARTNER
- print/mail/fulfilment — BROKER
- promotional merchandise / standardized goods — BROKER

## Explicit supersessions

- `ICT_HARDWARE_VAR France`: label rejected only; `Var` geography ≠ Value Added Reseller. Records preserved.
- broad procurement-agent France classification: superseded; records preserved.
- old PPE/EPI matcher: superseded; records preserved.
- open-world example attribution v1: superseded by composite-key v2.
- USA broad court-reporting/interpreting counts: superseded by strict v3.2 network authority.
- information-work v1/v2/v3.0 strategic pure counts: v3.1 is pure-core authority; earlier layers remain recall evidence.
- Australia review v3.0 title-only: invalid because AusTender titles are often opaque references.
- Australia broad PROGRAM_EVALUATION v3.1: superseded by v3.2 policy/test/generic split.
- failed USA network v3.0/v3.1 computes produced no strategic authority; v3.2 is first successful authority.

## Next analysis order

1. Build **unit-economics / margin / capital / credential** models for Tier A and A- lanes using historical value distributions and supplier models.
2. For USA court reporting / interpretation, split **remote vs onsite** and infer certification/geography friction from historical titles/buyers without claiming current eligibility.
3. For AU independent reviews / policy evaluations, decompose deliverables into desk research, stakeholder work, specialist sign-off and final report; identify small-repeat specialist suppliers.
4. Deep-dive the fragmented **toner/office consumables** cohorts and benchmark historical buyer recurrence/supplier concentration before any supplier quote exercise.
5. Continue open-world native-code review beyond the current top 1,000 unknowns; do not return to regex-only discovery.
6. Consolidate adjudicated lanes into the next deduplicated Atlas version without double-counting prior lanes.
