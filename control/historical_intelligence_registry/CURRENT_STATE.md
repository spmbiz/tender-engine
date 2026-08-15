# Historical Intelligence — Current State

Updated: 2026-08-16 (Europe/Brussels project session)

## Scope firewall

**Historical archive analysis only.** Live tenders and DCE evidence are not inputs to the findings summarized here.

## Canonical corpus authority

`control/historical_commercial_miner_v1/MASTER_SUMMARY.json`

- procurement records scanned: **18,271,075**
- award rows scanned: **20,307,312**
- award↔supplier links scanned: **19,958,186**
- Global Core v4: **2,250,547 notice-first** records
- USAspending: **15,842,317 award-first** records
- AusTender: **178,211 award-first** records

## Persistence / no-loss system

Authoritative policy: `README.md` + `ANALYSIS_PROTOCOL.md` in this directory.

Hard rule: **REJECTED_CLASSIFICATION ≠ REJECTED_RECORD.**

- No historical record is deleted because a classifier, regex, ontology or GPT hypothesis was wrong.
- Misclassified records remain available for open-world reclassification.
- Facts, classifications, model hypotheses and verdicts are separate layers.
- Corrections are superseded/versioned, never silently overwritten.

Decision ledgers now include:
- `CLASSIFICATION_DECISIONS.jsonl`
- `OPEN_WORLD_DECISIONS_2026-08-16.jsonl`
- `DEEP_DIVE_DECISIONS_2026-08-16.jsonl`
- `INFORMATION_WORK_DECISIONS_2026-08-16.jsonl`

Strategic hypotheses:
- `MODEL_HYPOTHESES.md`
- `ASYMMETRY_SCORECARD_V1.md`

## Known-opportunity map

`control/spm_historical_opportunity_atlas_v4/ATLAS_V4.md` contains the pre-current-expansion **90-lane** map. New adjudicated lanes below should be folded into the next Atlas version only after dedupe against v4.

## Open-world discovery — current authority v2

`control/historical_open_world_unknowns_v2/summary.json`

After excluding obvious already-known lane text from high-signal clusters while preserving all underlying records:
- semantic candidates: **24,657**
- code-only / weak-signature candidates: **1,842**
- semantic review queue: **3,000**
- code-only review queue: **1,500**

v2 fixes the v1 example-attribution bug by joining examples on the full commercial-cluster key rather than phrase signature alone.

## Australia — recruitment, digital learning and review/evaluation

Current structural authority: `control/historical_australia_asymmetric_services_v2/`
Semantic authority: `control/historical_australia_asymmetric_services_qa_v2/QA_PACKET.md`

Strongest adjudicated expansions:

- **General recruitment/search**: 2,130 awards · 94 buyers · 359 normalized supplier keys · top normalized supplier **6.6%** · median ~AUD23.5k — **PROMOTED / VERY HIGH**.
- **Executive search**: 118 · 40 buyers · 46 normalized keys · top **14.4%** · median ~AUD36k — **PROMOTED / HIGH**.
- **Digital/e-learning/platform/content**: 92 · 51 buyers · 56 normalized keys · top **19.6%** · median ~AUD61.1k — **PROMOTED / HIGH**, but more concentrated than v1 suggested.
- **Training design/content**: 162 awards — **HOLD** as a broad lean lane because Defence/specialist/instructor-heavy work is mixed with real content-design work.
- **Project/program assurance review**: 606 awards · 18 buyers · 115 normalized keys · top ~5.9% — structurally real; credential burden still under analysis.
- **Program evaluation**: 258 · 40 buyers · 166 normalized keys · top ~3.9% — structurally real; delivery model needs further segmentation.

Description-backed QA explicitly confirms wording such as Personnel Recruitment, Recruitment Services, Bulk Recruitment and Executive Search Services.

## USA — expert networks, court reporting and interpretation

Current precision authority: `control/historical_usa_knowledge_local_services_v2/`
Semantic authority: `control/historical_usa_knowledge_local_services_qa_v2/QA_PACKET.md`

Precision findings:

- **Expert witness**: **11,681 awards · 241 buyers · 2,648 suppliers · median ~$7.8k · top share 4.7%**.
  - heuristic supplier shape: 8,017 awards / 1,754 suppliers are organization-like vs 3,664 / 894 individual-like.
  - **Expert-network/intermediary thesis PROMOTED as a hypothesis**, not yet proven as the dominant winner archetype.
- **Litigation consultant**: 658 · 53 buyers · 262 suppliers · median ~$16.6k · top 3.7%.
- **Court reporting precision**: **5,204 · 260 buyers · 358 suppliers · median ~$3.8k · top 14.0%** — **PROMOTED**. v1 broad 12,478 is superseded due notebook/renovation contamination.
- **Language interpretation precision**: **1,017 · 260 buyers · 216 suppliers · median ~$17.3k · top 7.6%** — **PROMOTED**. v1 broad 23,666 is superseded due non-language interpretation contamination.
- Precision QA shows recurring agency-like winners in court reporting and genuine phone/video/sign-language interpretation examples.

USAspending is award-first. These facts do not prove open competition, current set-aside eligibility or contract-vehicle access.

## Information-work — newest asymmetric branch

### Recall layer v1
`control/historical_information_work_v1/`

- 4,816 broad historical matches
- 4,446 initially digital-first/remote-plausible

v1 is **recall/discovery only**. QA revealed major collisions: generic French `catalogue` procurement wording, medical scanner equipment in digitization, and scope-only data terminology. No records were deleted.

### Precision authority v2
`control/historical_information_work_v2/`

Global Core 2,250,547 notice-first records scanned; **525 precision information-work notices** retained.

Main precision families:
- Content/data migration: **165**
- Document digitization services: **82**
- Data entry/keying: **57**
- Data cleaning/enrichment/MDM: **50**
- Data collection/research: **48**
- Evidence/literature synthesis: **37**
- Metadata/cataloguing/indexing: **24**
- eDiscovery/document review: **17**
- Desk research/benchmarking: **17**
- Document/data conversion: **12**
- OCR/text extraction: **9**
- Data validation/coding: **4**
- Data annotation/labeling: **1**

Delivery composition:
- **421 digital-first / remote-plausible**
- 76 physical-input-likely
- 17 legal-specialist-risk
- 8 physical-storage/input
- 3 onsite/location-dependent

### Strict SPM asymmetry view
`control/historical_information_work_asymmetry_v1/summary.json`

Of the 525 precision rows, **149 are both TITLE_SIGNAL and digital-first**.

Strongest explicit title-led digital surfaces by volume:
- Data collection/research: **36**
- Data cleaning/enrichment/MDM: **27**
- Content/data migration: **44**
- Evidence/literature synthesis: **13**
- Data entry/keying: **7**
- Metadata/cataloguing/indexing: **7**
- OCR/text extraction: **4**

Important semantic/business verdicts:
- **Data entry/keying — PROMOTED / VERY HIGH ASYMMETRY.** QA includes open-bid Data Capture Services with explicit error-rate/security/turnaround requirements and explicit `Saisie de données` work.
- **Evidence/literature synthesis — PROMOTED / VERY HIGH ASYMMETRY.** QA includes PHAC rapid scientific evidence reviews; domain credentials can still be required on specific opportunities.
- **Desk research/benchmarking — PROMOTED / HIGH ASYMMETRY.** QA includes an explicit Belgian desk-research market study.
- **Data collection/research — PROMOTED / HIGH CONDITIONAL.** Remote/document/web collection is attractive; fieldwork subsets are not equally lean.
- **Data cleaning/enrichment/MDM — PROMOTED / HIGH CONDITIONAL.** Real MDM/data-quality market, but enterprise platform implementations must be separated from actual data operations.
- **Content/data migration — HOLD as one broad lean lane.** Pure migration jobs exist, but many large SAP/KIS/platform projects merely include migration.
- **Metadata/cataloguing/indexing precision subset — PROMOTED / MEDIUM-HIGH.** v1 broad `catalogue` family is explicitly rejected; v2 strict family is the only promotable subset.
- **Document digitization — PROMOTED as BROKER/HYBRID, not pure AI.** Physical custody/intake dominates many jobs.
- **OCR/text extraction — HOLD / VERY HIGH ASYMMETRY, LOW SAMPLE.** Expand multilingual discovery without loosening precision.
- **Data annotation/AI labeling — PROMOTED HYPOTHESIS, LOW SAMPLE.** One exact Digital Africa labeling procurement is exceptionally on-thesis but not a market-size proof.
- **eDiscovery — HOLD / legal-specialist risk.**

## Highest-priority SPM asymmetric theses now

1. **Information-work automation** — data entry, evidence synthesis, desk research, selected data cleaning, OCR/extraction, validation, metadata, remote data collection.
2. **Recruitment/search/matching** — candidate sourcing/matching itself is a recurring public-sector product, not merely a staffing adjacency.
3. **Contractor/talent brokerage** — Australia ICT/digital roles remain broadly fragmented.
4. **Digital learning/content** — real market, especially content/e-learning/platform work, but platform concentration matters.
5. **Translation/transcription/DTP/accessibility/media-monitoring** — previously validated AI-compressible lanes remain core.
6. **Print/mail/fulfilment + standardized-goods sourcing** — supplier/geographic arbitrage is strong where logistics/cash burden stays manageable.
7. **Expert/language service networks** — expert witness, court reporting and interpretation now have real historical structure; licensing/credentials/access require separate economics.
8. **Review/evaluation** — attractive when the output is document/evidence analysis; specialist credential requirements can dominate.

## Explicitly corrected / superseded interpretations

- `ICT_HARDWARE_VAR — France`: false label (`Var` geography vs Value Added Reseller); records preserved/reclassified.
- `PROCUREMENT_AGENT — France`: broad centrale-d'achat wording did not mean supplier-as-procurement-agent; records preserved.
- old PPE/EPI matcher: superseded after EPIC/EPICERIE/Kiltipper collisions.
- open-world v1 example attribution: superseded by v2 composite-key attribution.
- USA broad court-reporting and interpretation counts: superseded by precision v2.
- information-work v1 broad catalogue/metadata/digitization counts: recall-only; v2 precision authority.

## Next analysis order

1. Split **PURE_DATA_MIGRATION** from platform implementations containing migration.
2. Expand **OCR / extraction / annotation / redaction / metadata** multilingual terminology while retaining strict semantic QA.
3. Decompose **expert-witness winners** into direct experts vs consulting firms vs true expert-network/placement intermediaries.
4. Decompose AU **program evaluation / assurance review** by deliverable and credential burden.
5. Build **margin/capital/barrier model** for top asymmetric lanes: unit labor compression, subcontractor cost, working capital, insurance, licenses, locality, panel/channel requirements.
6. Continue ontology-independent review beyond the current 3,000 semantic + 1,500 code-only queues.
7. Fold adjudicated new lanes into the next Atlas version only after dedupe against v4.
