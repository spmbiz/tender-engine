# SPM Historical Opportunity Atlas — v5 Expansion Addendum

**Historical-only. No live tender / DCE / current eligibility conclusion.**

This is an addendum to Atlas v4, not a naive row-count increment. New/refined lanes are listed with lineage so the eventual v5 merge can deduplicate overlaps rather than double-count related markets.

## Newly adjudicated / materially refined lanes

| Lane | Geography / grain | Historical evidence | SPM read | Status | Lineage / dedupe note |
|---|---|---|---|---|---|
| General recruitment / candidate search | Australia award-first | 2,130 awards · 94 buyers · 359 normalized supplier keys · top 6.6% | sourcing/matching automation | **PROMOTE** | distinct from existing ICT contractor bodyshopping lanes |
| Executive search | Australia award-first | 118 · 40 buyers · 46 normalized keys · top 14.4% | high-fee search; credibility-heavy | **PROMOTE** | child of recruitment, keep distinct economics |
| Digital learning / e-learning / platform-content | Australia award-first | 92 · 51 buyers · 56 normalized keys · top 19.6% | AI courseware/content adjacency | **PROMOTE** | dedupe against any generic training/e-learning hold row |
| Court reporting / deposition reporting | USA award-first precision | 5,204 · 260 buyers · 358 suppliers · median ~$3.8k | network/agency operations | **PROMOTE** | distinct from generic transcription |
| Language interpretation | USA award-first precision | 1,017 · 260 buyers · 216 suppliers · median ~$17.3k | remote interpreter-network potential | **PROMOTE** | distinct from written translation |
| Expert-witness / specialist network | USA award-first precision | 11,681 · 241 buyers · 2,648 suppliers | expert discovery/matching thesis | **PROMOTED HYPOTHESIS** | do not equate all direct expert awards with intermediary wins |
| Data entry / keying / capture | Global Core notice-first precision | 57 notices · 35 buyers; explicit data-capture SLAs | extremely AI-compressible | **PROMOTE** | likely new lane |
| Evidence / literature synthesis | Global Core notice-first precision | 37 · 28 buyers; 13 title-led digital-first | search/extract/synthesize automation | **PROMOTE** | separate from broad research/survey lane |
| Desk research / benchmarking | Global Core notice-first precision | 17 · 15 buyers | agentic-research edge | **PROMOTE** | dedupe carefully against broad market-research rows |
| Data collection / research operations | Global Core notice-first precision | 48 · 42 buyers; 36 title-led digital-first | strong remote subset; fieldwork caveat | **PROMOTE CONDITIONAL** | separate remote collection from field survey work |
| Data cleaning / enrichment / MDM operations | Global Core notice-first precision | 50 · 34 buyers; 27 title-led digital-first | strong data-pipeline edge | **PROMOTE CONDITIONAL** | split data-ops from enterprise MDM implementation in next pass |
| Metadata / cataloguing / indexing — precision | Global Core notice-first precision | 24 · 17 buyers; 7 title-led digital-first | automatable small market | **PROMOTE** | explicitly supersedes false 904-record v1 `catalogue` family |
| Document digitization — physical-input | Global Core notice-first precision | 82 · 72 buyers | broker/local partner + OCR workflow | **PROMOTE AS HYBRID** | do not merge blindly with digital OCR/extraction |
| OCR / text extraction | Global Core notice-first precision | 9 strict; 4 title-led digital-first | huge AI edge but low observed sample | **HOLD / EXPAND DISCOVERY** | likely under-recalled terminology |
| Data annotation / AI labeling | Global Core notice-first precision | 1 exact Digital Africa procurement | ideal AI+human-QA mechanics | **PROMOTED HYPOTHESIS / LOW SAMPLE** | not yet a market-size row |
| Content/data migration | Global Core notice-first precision | 165; 44 title-led digital-first | pure migration attractive, platform bundles not uniformly lean | **HOLD BROAD / DECOMPOSE** | split PURE_MIGRATION before final Atlas row |

## Explicit non-additions / corrections

- `ICT_HARDWARE_VAR — France`: **do not add as VAR**. Classification false; underlying records preserved for real-category reclassification.
- `PROCUREMENT_AGENT — France`: **do not add as one procurement-agent lane** from the broad regex. Records preserved.
- information-work v1 `CATALOGUING_METADATA_INDEXING` 904: **do not add**. Generic `catalogue` procurement wording contaminated it. Only v2 precision subset is promotable.
- USA v1 court reporting 12,478 and interpretation 23,666: **do not use**. Precision v2 counts supersede them.
- generic training: do not promote wholesale; digital learning is promoted, training-design/content remains partially held.

## Merge rule for eventual Atlas v5

A new row should enter the canonical Atlas only when:

1. semantic classification is supported by representative title/scope evidence;
2. the row is deduped against existing lane definitions;
3. its historical grain is explicit (`NOTICE_FIRST` vs `AWARD_FIRST`);
4. market facts are separated from SPM-specific model hypotheses;
5. any superseded classifier/count is linked rather than erased.

This addendum is therefore the durable expansion queue for the next deduplicated Atlas build.
