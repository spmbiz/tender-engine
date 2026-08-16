# OSS / Open-Data Tender Provider Expansion Skill

## Purpose

This skill is a living implementation backlog for expanding `tender-engine` with high-value public procurement providers, open datasets, OSS reference implementations, historical intelligence, and reusable ingestion/document-processing bricks.

Use it when asked to add countries, improve discovery coverage, add historical award intelligence, improve DCE/document acquisition, reduce browser cost, build local mirrors, or strengthen provider abstractions.

The objective is **not** to accumulate scrapers. The objective is to turn each useful upstream/source into a stable provider behind the existing tender-engine pipeline while preserving its strict fail-closed behavior.

---

## Existing pipeline and coverage: preserve first

The current repo already describes a pipeline broadly like:

```text
broad official discovery
  -> normalize/dedupe
  -> GPT wide read
  -> DCE candidate queue
  -> portal-aware fanout
  -> DCE download
  -> recursive extraction
  -> manifest + SHA-256
  -> mandatory-gate deep read
  -> final rescore
```

Known existing discovery rails include **TED**, **Contracts Finder**, and **eTenders Ireland**. Browser/DCE fanout and autonomous fleet logic also already exist.

Before adding any source from this skill, inspect current providers, workflows, config, skills, state, and historical warehouse tables. A source named below may have been implemented after this skill was written.

---

## Non-negotiable safety / truth rules

1. **Inspect first. Extend, do not duplicate.** If a country/source already has an adapter, improve it rather than adding another competing implementation unless a second independent rail materially improves recall/resilience.
2. Prefer **official bulk data/API/export > public HTTP > browser**.
3. Preserve existing semantics: **UNKNOWN stays UNKNOWN**.
4. Login/MFA/CAPTCHA/auth-wall remains an explicit non-success unless legitimate user-owned credentials and the repo's policy explicitly allow access.
5. Never fabricate eligibility, mandatory criteria, dates, values, documents, buyer/supplier identities, or award history.
6. No FINAL SUPER GREEN / high-confidence qualification without the repo's required verified mandatory gates.
7. Every normalized field should retain source/provenance where technically practical.
8. Before code reuse, re-check upstream license and current source access/ToS. If license is absent/unclear/incompatible, use only as architecture/reference.
9. Never adopt CAPTCHA-solving/OCR as a bypass mechanism. OCR is for legitimate document parsing, not defeating access controls.
10. Provider failures must be observable and bounded with retries, rate limiting, circuit breakers, and checkpoints.

---

# Recommended provider contract

Adapt to the repo's existing abstractions rather than forcing this exact interface, but preserve the capabilities:

```python
class TenderProvider:
    def discover(self, window_or_cursor): ...
    def fetch_detail(self, source_id): ...
    def fetch_documents(self, source_id): ...
    def normalize(self, raw): ...
    def checkpoint(self): ...
    def healthcheck(self): ...
```

Each provider should emit or allow recovery of:

```yaml
provider: source-name
source_id: native-id
source_url: https://...
observed_at: ...
raw_hash: sha256:...
canonical:
  notice: {}
  procedure: {}
  lots: []
  buyers: []
  suppliers: []
  awards: []
  documents: []
evidence:
  field_name:
    value: ...
    confidence: ...
    observations:
      - source_url: ...
        source_type: api|bulk|html|document|registry|derived
        observed_at: ...
        snippet_or_hash: ...
```

Provider fixtures should cover normal notices, amendments, awards, missing fields, pagination/cursor boundaries, duplicate/republication behavior, and access failures.

---

# P0 — implement/evaluate first

## 1. Morocco — `automatebdarija/pmmp-scraper`

Why interesting:

- reference implementation for the Moroccan PMMP / Portail Marocain des Marchés Publics;
- Python + Chromium/cron + PostgreSQL style ingestion;
- includes DCE-oriented workflow and credential configuration in upstream documentation.

How to use it:

- first inspect whether Morocco/PMMP already exists in `tender-engine`;
- use it as a blueprint for a `PMMPProvider` / document resolver;
- keep credentials strictly user-owned/authorized and secret-managed;
- do not turn user-agent/credential handling into access-control bypass logic;
- persist raw notice/document provenance and explicit failures.

## 2. Switzerland — `Digilac/simap-mcp`

Very strong candidate.

Upstream exposes SIMAP public procurement concepts including tender search/detail, CPV, cantons, institutions, publication history and procurement-office metadata. At research time it documented the SIMAP API as public/read-only and the repo as MIT; re-check before implementation.

Preferred implementation:

- implement a native provider against the underlying public SIMAP API where practical rather than making MCP itself a hard runtime dependency;
- use publication-history links to join amendments/republications into one procedure timeline;
- map Swiss-specific codes/metadata without losing original values.

Potential enrichment reference: `malkreide/swiss-public-data-mcp` for public Swiss registries/official datasets such as company/notice data. Prefer official first-party sources when accessible.

## 3. Norway — Doffin official API

Useful references:

- `EnzoConsulting/doffin-dashboard`
- `anskaffelser/eforms-sdk-nor`
- `reidar80/DoffinMCP`

The important finding is architectural: **Doffin has an official API**, so Norway should be API-first rather than browser-first.

Implementation priorities:

- inspect current Norway coverage;
- use official Doffin API semantics and current authentication/subscription requirements;
- CPV/keyword/date paging with durable cursor/checkpoint;
- normalize eForms without throwing away Norwegian-specific fields;
- browser fallback only for data/documents not exposed through the public API.

## 4. Germany — `leelesemann-sys/vergabe-radar`

One of the strongest architecture references.

Useful patterns:

- an extensible `TenderSource` abstraction;
- official `oeffentlichevergabe.de` ingestion;
- daily/bulk CSV-style acquisition;
- normalized relational tables followed by a flattened search document;
- local search/indexing and geocoding;
- source-specific import order.

Borrow the architecture, **not** the Azure dependency. Tender-engine can keep its own storage/search stack.

Recommended pattern:

```text
official/raw source tables
  -> canonical relational model
  -> flattened retrieval/search document
  -> historical + live intelligence
```

This is a strong model for scaling to dozens of country providers without contaminating the canonical schema with provider-specific parsing logic.

## 5. France — BOAMP live + DECP historical

Useful references:

- `stefw/boamp-server` — BOAMP API search/detail reference;
- `mdaoudi-de/hackathon-an-2026-vigie-marches` — useful DECP/data.gouv historical-query patterns;
- `OneNicolas/mcp-service-public` — broader French public-data/company enrichment reference; inspect its current tool set rather than assuming BOAMP is still included.

Target architecture:

```text
live candidate
  -> buyer SIRET / canonical buyer
  -> DECP historical contracts/awards
  -> previous winners + amounts + CPVs + cadence
  -> incumbent pressure / competition priors
  -> tender reasoning
```

For large history, prefer current official/data.gouv queryable resources or Parquet/bulk files over repeatedly scraping pages.

Do not freeze historical row counts/file sizes/rate limits into code; discover current metadata at runtime or config time.

## 6. Portugal — `chicoferreira/contratopublico`

Useful pattern: build and query a **local mirror** of slow public-contract source data instead of repeatedly querying the upstream search UI.

The project continuously ingests Portal BASE data into PostgreSQL + Meilisearch. At research time it was MIT.

Borrow:

- incremental scraper loop;
- local canonical storage;
- fast search index over the mirror;
- monitoring/benchmark mindset.

Do not assume the current Portal BASE API is sufficient; inspect official API/export capability at implementation time and prefer it when it provides adequate coverage.

## 7. Estonia — `keeltekool/hanke-radar`

High-value pattern from its product/design documentation:

```text
bulk monthly/open-data XML
  -> cheap ingest
  -> shortlist
  -> individual notice HTML/API enrichment only when needed
```

This is the **BULK CHEAP -> DETAIL EXPENSIVE** rule. Use it broadly across countries whenever official bulk dumps exist.

At implementation time verify the current Estonian RHR public endpoints and schemas instead of hardcoding stale endpoint assumptions from a reference repo.

## 8. Australia — federal + NSW

Candidates:

- `austender/austender-ocds-api`
- `NSW-eTendering/NSW-eTendering-API`

NSW's official developer repo documents machine-readable tender/planned-procurement/contract data and OCDS compatibility. This is strategically important: Australian coverage should not stop at federal AusTender; add state-level providers where the marginal coverage is material.

Pattern:

- one canonical Australia model;
- independent federal/state source IDs;
- OCDS-compatible fields mapped without losing native source references;
- planned procurement as pre-tender radar when available.

---

# P1 — high-value expansion / intelligence references

## Austria — `Forum-Informationsfreiheit/OffeneVergaben-Scraper`

Important idea: **discover the publishers/sources dynamically** from a government CKAN/open-data catalog, validate them, disable broken publishers, and ingest only new/updated records.

This can become a generic `SourceRegistryCrawler` pattern for jurisdictions where the central catalog points to many distributed publisher feeds.

## Poland

References:

- `atlasprzetargow/mcp-server`
- `atlasprzetargow/polish-tenders-dataset`

The open dataset is especially interesting for historical buyer/contractor/notice analysis. At research time public dataset outputs were CC BY 4.0 and export code MIT; verify current release/schema/licensing.

Use historical data for:

- buyer cadence;
- supplier recurrence;
- competition intensity;
- CPV/category priors;
- geographic patterns;
- likely incumbents;
- award/value distributions.

## Brazil

References:

- `Licinexus/licinexus-mcp`
- `Mcp-Brasil/mcp-brasil`

Interesting because Brazil's PNCP/ComprasNet/SIASG ecosystem can expose not only notices/contracts but also **annual procurement plans (PCA)**. PCA should be treated as a pre-tender radar: future demand before formal tender publication.

Prefer official PNCP/public APIs underneath reference implementations where possible.

## Chile

References:

- `stgomoyaa/mercadopublico-parser`
- `DCCP-Hugo/MercadoPublicoOCDS`
- `jmadasme/licitaciones-mercado-publico`

Useful patterns include typed normalization, rate limits/retries, tender+award parsing, bulk OCDS relational storage, and resilient document downloads.

`jmadasme/licitaciones-mercado-publico` previously had unclear licensing in research: inspect/learn only unless a compatible license is confirmed.

## Sweden — `isakskogstad/Upphandlingsdata-MCP`

Potential enrichment/provider reference combining Swedish procurement authority data, TED Swedish procurement, domain-specific procurement knowledge, and auxiliary criteria data. Verify first-party Swedish APIs behind it and favor direct official access.

## Czech Republic — `Boza-Analytics/Smart-Tender-Search`

Reference for scheduled ingestion + queue/fanout + semantic/LLM relevance filtering. Useful architecture ideas, but do not make a cloud-specific small project foundational if the current tender-engine fleet already provides equivalent scheduling/fanout.

## Italy — official `anticorruzione/npa`

Official ANAC NPA/PCP/FVOE technical/OpenAPI material is valuable for:

- Italian procurement lifecycle/data model;
- eForms semantics;
- interoperability requirements;
- identifying legitimate integration surfaces.

Do not assume every documented production service is an unauthenticated discovery API. Some services may require PDND/certified-platform access. Keep access requirements explicit.

---

# P2 — architectural/reference bricks

## `dobtco/openrfps-scrapers`

Old, but useful philosophy:

- many providers behind a common schema;
- per-provider fixtures/cached test data;
- provider-specific implementation with common invariants.

Steal the **provider contract + regression fixture** mindset, not stale endpoints.

## `open-contracting/kingfisher-collect` + Kingfisher Process

Strong reference for collecting many OCDS data sources, source registration, processing, and data pipelines. Inspect whether its abstractions can simplify importing OCDS-native providers without introducing unnecessary runtime complexity.

## `open-contracting/lib-cove-ocds`

Useful as an OCDS validation/quality-assurance reference. Consider using it or equivalent validation in an offline QA stage for OCDS sources.

## `openprocurement/openprocurement.api`

Reference for procurement API semantics and tender/auction domain modeling. Architecture/reference rather than default dependency unless there is a concrete integration need.

## `flexponsive/tap-eu-ted`

Singer/Meltano-style TED ingestion reference. Useful if tender-engine later standardizes provider ELT around taps/streams/checkpoints; do not duplicate the existing TED rail just to adopt a framework.

## `OP-TED/ted-open-data-explorer`

Useful for learning the EU eProcurement Ontology, RDF/SPARQL relationships, publication histories, and linking multiple notices belonging to one procurement procedure.

Potential upgrade: enrich the current TED model with a durable **procedure timeline / notice graph** rather than treating every publication as an isolated tender.

## US reference — GSA SAM/RFP scraper projects

Projects such as the previously identified GSA/SAM scraper references are useful for document-text extraction, database persistence, and scheduled ingestion. Re-verify the exact current repository and prefer official SAM.gov APIs/data feeds for production.

## Spain / historical corpora

`BquantFinance/licitaciones-espana` and similar public corpora can be useful for historical priors and parser regression tests. Verify freshness/licensing before relying on them for live discovery.

---

# Documents / DCE processing bricks

## `docling-project/docling`

High-priority evaluation for deep document parsing.

At research time Docling was MIT and supported PDF, DOCX, PPTX, XLSX, HTML, images and more, with layout/table understanding, OCR, Markdown/JSON export, and local execution.

Recommended tender pipeline:

```text
recursive unpack
  -> MIME/type classify
  -> native parser fast path
  -> Docling fallback/deep path where useful
  -> normalized Markdown/JSON/tables
  -> mandatory-gate extraction
  -> evidence offsets/page references
```

Do not send every easy text PDF through the most expensive parser. Keep the fast path and only escalate when structure/OCR/layout complexity justifies it.

## Document ZIP/storage pattern — `akashbalyan/tenderX`

Useful architectural idea:

```text
tender documents
  -> deterministic download
  -> archive integrity/hash
  -> recursive extraction
  -> object/durable storage
  -> metadata manifest
```

Do **not** copy CAPTCHA/OCR access-bypass behavior. In tender-engine, CAPTCHA remains explicit non-success unless policy is intentionally changed by the user.

---

# Historical Market Intelligence integration

Every live provider should eventually connect to the historical warehouse rather than stopping at discovery.

For a new candidate, derive when data supports it:

- buyer frequency and procurement cadence;
- buyer spend/value distribution;
- previous suppliers/winners;
- incumbent recurrence ratio;
- number of offers / competition where available;
- award discount/premium vs estimate;
- CPV and micro-niche behavior;
- geography and procedure-type patterns;
- seasonality;
- framework/lot recurrence;
- supplier concentration;
- buyer-supplier graph features;
- likely renewal windows;
- pre-tender signals from procurement plans.

Keep priors separate from verified current-tender facts. Historical inference must never overwrite a current mandatory criterion.

---

# Cross-provider entity resolution

Consider `moj-analytical-services/splink` or an equivalent probabilistic linkage layer for organizations that appear under different names/IDs across sources.

Tender use cases:

```text
buyer aliases -> canonical buyer
supplier aliases -> canonical supplier
national registry IDs -> canonical organization
TED + national source notice -> one procedure / linked publication
```

Features can include legal IDs, VAT/company IDs, normalized name, address, postcode, domain, phone, geography, and known source mappings.

Do not auto-merge weak matches without a reviewable score and evidence.

---

# Evidence/provenance model

`brightdata/open-enrich` is a useful reference for **citation/evidence per field**. Do not adopt its paid infrastructure by default; borrow the model.

Recommended concept:

```yaml
field:
  value: ...
  confidence: 0.93
  evidence:
    - source_url: ...
      source_type: official_api
      observed_at: ...
      snippet_or_hash: ...
```

For documents, also retain page/file/path offsets where possible so mandatory-gate decisions can be traced back to exact evidence.

---

# Provider prioritization formula

Do not prioritize by novelty. Score each candidate roughly on:

```text
incremental live coverage
+ historical intelligence value
+ document availability
+ official/stable access
+ pre-tender signal value
+ field richness
+ throughput
+ maintainability
------------------------------------------------
anti-bot fragility
+ browser cost
+ duplicate overlap
+ auth burden
+ legal/license uncertainty
```

A boring official bulk feed is usually more valuable than a clever browser scraper with the same data.

---

# Implementation sequence for future GPT/agent

When asked to implement providers from this skill:

1. Read `AGENTS.md`, `skills/tender-engine/SKILL.md`, and current provider/workflow code.
2. Search the repo for the country/source and verify whether it already exists.
3. Inspect current canonical schemas and historical warehouse grain before designing a new schema.
4. Re-verify upstream source/API/repo/license today.
5. Prefer bulk/API and incremental checkpoints.
6. Implement one provider behind the existing abstraction.
7. Add representative fixtures and failure fixtures.
8. Normalize without losing native IDs/source URLs.
9. Add provenance/evidence and source-health metrics.
10. Benchmark coverage and duplicate overlap against existing TED/national rails.
11. Wire to the DCE queue only after discovery/detail behavior is trustworthy.
12. Connect award/history fields to Market Intelligence where available.
13. Run bounded tests before enabling in autonomous fleet.
14. Update this skill to mark what became implemented and what remains.

---

# Definition of done

A provider expansion is complete only when:

- it does not duplicate an existing rail accidentally;
- pagination/cursors/checkpoints are deterministic;
- normalization and source IDs are stable;
- amendments/republications are handled or explicitly modeled;
- provenance survives into canonical data;
- documents are hashed/manifested where acquired;
- retries/rate limits/failures are bounded and visible;
- fixtures/regression tests cover success and failure;
- auth/CAPTCHA/MFA failures remain fail-closed;
- historical intelligence linkage is added when source data supports it;
- benchmark demonstrates incremental value;
- autonomous enablement cannot silently turn source failure into fabricated success.

Treat this file as a **living roadmap**. When a source is implemented, annotate the current provider path/config/tests here so future GPT agents extend the existing implementation instead of rediscovering or duplicating it.