# Historical Intelligence — Current State

Updated: 2026-08-16 (Europe/Brussels project session)

## Scope firewall

**Historical archive analysis only.** Live tenders and DCE evidence are not inputs to the findings summarized here.

## Canonical corpus authority

`control/historical_commercial_miner_v1/MASTER_SUMMARY.json`

- procurement records scanned: **18,271,075**
- award rows scanned: **20,307,312**
- award↔supplier links scanned: **19,958,186**
- Global Core v4: 2,250,547 notice-first records
- USAspending: 15,842,317 award-first records
- AusTender: 178,211 award-first records

## Persistence / no-loss system

Authoritative policy: `control/historical_intelligence_registry/README.md` + `ANALYSIS_PROTOCOL.md`.

Rules now enforced conceptually:
- no historical record is deleted because a classification/hypothesis is wrong;
- `REJECTED_CLASSIFICATION` means the mapping was wrong, not the procurement;
- misclassified records stay available for open-world reclassification;
- strategic GPT judgments are stored separately from measured FACTS;
- changed views are superseded, not silently overwritten.

Decision ledgers:
- `CLASSIFICATION_DECISIONS.jsonl`
- `OPEN_WORLD_DECISIONS_2026-08-16.jsonl`

Strategic hypothesis ledger:
- `MODEL_HYPOTHESES.md`
- `ASYMMETRY_SCORECARD_V1.md`

## Current known-opportunity map

`control/spm_historical_opportunity_atlas_v4/ATLAS_V4.md` tracks **90 historical lanes**. The Atlas is a map, not an exhaustive ontology.

Major families already supported:
- web/CMS/support/redesign;
- translation/transcription/DTP/design/digitization/accessibility;
- print/mail/fulfilment;
- software resale/VAR;
- standardized goods;
- public-sector staffing/contractor brokerage;
- USA admin/procurement-support/BPO;
- travel/media/freight/other intermediary models.

## Open-world discovery

`control/historical_open_world_unknowns_v1/summary.json`

After deliberately excluding obvious known-lane text from high-signal clusters:
- **27,096** not-yet-named candidate clusters remain;
- **1,000** were placed into a diversity review queue;
- source records remain untouched.

Economic-mechanism lens:
`control/historical_open_world_asymmetry_lens_v1/summary.json`

Among the 1,000 reviewed unknown clusters, 99 cluster×mechanism pairs were tagged for deeper review, including training, expert networks, recruitment, local-service aggregation, lodging, leasing, events, assurance/review, interpretation, hardware distribution and telecom aggregation.

## New Australia decomposition — strongest current expansion

`control/historical_australia_asymmetric_services_v1/`

Across 178,211 AusTender records, the new decomposer identifies 14,343 rows in recruitment/training/review/event families.

Strongest emerging submarkets:
- General recruitment/search: **2,130 records · 94 buyers · 536 suppliers · top supplier 3.1% · median AUD 23.5k**
- Executive search: **118 · 40 buyers · 62 suppliers · top 6.8% · median AUD 36.0k**
- Training design/content: **162 · 45 buyers · 144 suppliers · top 2.5% · median AUD 52.7k**
- Digital/e-learning/platform/content: **92 · 51 buyers · 70 suppliers · top 8.7% · median AUD 61.1k**
- Project/program assurance review: **606 · 18 buyers · 120 suppliers · top 5.9% · median AUD 17.6k**
- Program evaluation: **258 · 40 buyers · 185 suppliers · top 3.1% · median AUD 179k**
- Independent specialist review: **61 · 30 buyers · 58 suppliers · top 3.3% · median AUD 105.7k**
- Event management: **267 · 35 buyers · 229 suppliers · top 2.6% · median AUD 33.2k**

These are award-first historical facts. Current panel/access/licensing requirements remain UNKNOWN.

## Highest-priority asymmetric hypotheses now

1. **Document/content/data operations** — translation, transcription, OCR/digitization, DTP, accessibility, technical writing, research/data cleaning, monitoring.
2. **Recruitment/search/matching** — especially pure candidate search and executive recruitment, not merely bodyshopping.
3. **Digital training design / e-learning content** — now empirically separated from generic instructor-led training.
4. **Contractor/talent brokerage** — AU ICT/digital role market remains highly fragmented.
5. **Standardized-goods sourcing** — where specs/logistics/cash burden are manageable.
6. **Print/mail/fulfilment brokerage** — strong EU sourcing arbitrage, physical execution caveats.
7. **Review/evaluation work** — potentially attractive when deliverable is document/evidence analysis rather than licensed physical inspection.

## Active analyses

- Australia semantic QA packet: representative titles + winners + buyers for recruitment/training/review/events.
- USA aggregator-services decomposer: expert witness, litigation consultant, court reporting, interpretation, local subcontractable services and lodging.

## Explicitly superseded / corrected interpretations

- `ICT_HARDWARE_VAR — France`: **classification rejected only**. `Var` generally meant the French geography/département, not Value Added Reseller. All underlying records remain preserved and must be reclassified by actual subject.
- `PROCUREMENT_AGENT — France`: broad family interpretation rejected; many records merely involved a centrale d'achat. Records preserved.
- old PPE/EPI short-token matcher: superseded because `EPI`/`PPE` collided with unrelated strings; word-boundary version is current.
- rental/leasing mechanism tag on court-reporting: mechanism assignment rejected; court-reporting records preserved for legal/document-service analysis.

## Next analysis order

1. semantic QA recruitment + digital training + review/evaluation;
2. buyer/winner archetypes and repeat behavior;
3. USA aggregator-service economics;
4. gross-margin / capital / licensing / local-delivery friction model;
5. continue ontology-independent mining beyond the first 1,000 unknown clusters;
6. promote new lanes into the Atlas only after semantic QA.
