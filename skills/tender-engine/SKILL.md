---
name: tender-engine
description: Operate the SPM Business public-tender intelligence engine end to end: high-recall discovery, historical priors, live scoring, selective DCE retrieval, mandatory-gate verification, durable preservation, and bid/no-bid classification.
---

# Tender Engine — Canonical Operating Skill

Use this skill for public-procurement harvesting, historical market intelligence, live tender discovery, DCE/document retrieval, opportunity scoring, and SPM Business bid/no-bid work.

## Mission

Find public tenders that SPM Business can fulfill leanly with AI, software, subcontracting, resale, brokerage/middleman execution, or other low-fixed-cost delivery models. Optimize for expected profit, feasibility, low competition/friction, and execution speed — without narrowing discovery so aggressively that unusual profitable niches disappear.

The operating loop is:

**MASS DATA → HISTORICAL INTELLIGENCE → LIVE HIGH-RECALL DISCOVERY → PRELIMINARY RANKING → SELECTIVE DCE → MANDATORY-GATE VERIFICATION → FINAL BID / NO-BID**

## Non-negotiable evidence rules

1. **Missing evidence is UNKNOWN, never zero, false, or assumed satisfied.**
2. Never label an opportunity `FINAL_SUPER_GREEN` or score it **90+** until mandatory eligibility and delivery gates are verified from the DCE or an authoritative equivalent.
3. Notice-level evidence can support a strong preliminary candidate, but not a final eligibility conclusion when turnover, references, certifications, staffing, insurance, submission conditions, deliverables, or subcontracting constraints remain unclear.
4. Historical competition is a prior, not proof of live ease. `median_bidders = 1` can coexist with hard reseller, certification, framework, local-presence, or reference requirements.
5. For software/licensing/cloud/cyber/hardware/AV categories, explicitly carry `PARTNER_OR_RESELLER_REQUIREMENT_POSSIBLE` until the live documents resolve it.
6. Do not bypass authentication, CAPTCHA, MFA, access controls, controlled attachments, or portal restrictions. Classify the barrier faithfully.
7. Preserve authoritative identifiers and provenance. Do not fuzzy-dedupe two notices merely because title/value/buyer look similar.
8. National notice-first datasets can overlap TED. Deduplicate only on evidence-bearing exact/canonical identifiers or high-confidence deterministic linkage.
9. USAspending federal records are **award-first evidence**, not reconstructed original SAM.gov opportunity notices. Keep award-first lanes analytically separable from notice-first opportunity data.
10. Do not mix currencies in rankings or totals unless a sourced FX normalization is explicitly applied.

## Data preservation contract

**NEVER DELETE UNIQUE HARVESTED DATA MERELY TO SAVE GITHUB ACTIONS ARTIFACT SPACE.**

Actions artifacts are a temporary transport/debug layer, never the canonical datastore.

For every valuable harvest:

- Preserve raw/original procurement files when publicly retrieved.
- Preserve candidate identity, source URL, source notice ID, timestamps, manifests, routes, status, hashes, and extraction provenance.
- Preserve SHA-256 or equivalent integrity metadata for canonical files.
- Persist durable data to the canonical GitHub Release/data store **before** removing any temporary Actions artifact.
- Any cleanup must be **copy → verify size/hash/presence → only then delete temporary duplicate**.
- If durable upload or verification fails, retain the source artifact/data.
- Never delete a unique DCE, corpus, manifest, route result, gate snippet, or harvest record as a storage optimization.
- Avoid duplicating fully unpacked trees when the original archive + manifest/hash is sufficient to reconstruct them; derived/reconstructible caches may be omitted.

Canonical GitHub Release assets should include, as applicable:

- exact candidate queue and selection provenance;
- original public DCE/document package per candidate;
- canonical manifest/index with hashes;
- compact extracted corpus/evidence;
- mandatory-gate snippets;
- aggregate summary/deep-review pack.

## Source and registry discipline

Before quoting global counts, source coverage, or warehouse status, read the current warehouse registry/manifest in the repository. Treat registry content as more authoritative than remembered counts.

Maintain grain explicitly:

- `NOTICE_FIRST_TENDER`
- `AWARD`
- `AWARD_SUPPLIER_LINK`
- `AWARD_FIRST_PROCUREMENT`
- buyer/supplier dimensions

Do not casually sum these grains into "unique tenders". It is acceptable to describe a broader volume as procurement records/facts when the grains are named.

For historical TED, official bulk XML packages are authoritative. For current live TED work, use official notice/API/XML routes and the downstream document portal exposed by the notice.

## Discovery strategy

Discovery must be broad enough to discover unknown profitable niches.

Preferred pattern:

1. Harvest the full feasible live source window.
2. Canonicalize and exact-dedupe.
3. Apply historical priors and known SPM ontology.
4. Run open-world/cohort discovery over residual notices rather than discarding them.
5. Wide-read sufficiently broad candidate packets when recall matters.
6. Rank only after coverage is audited.

Do not restrict the engine to obvious web/AI keywords. Relevant lean opportunities can include, among others:

- websites, portals, APIs, low-code, RPA, SaaS and software support;
- data migration, BI, DMS, scanning, archiving and document processing;
- transcription, translation, editorial/copywriting and research/evaluation;
- graphic design, video, motion, photography, advertising, PR and media placement;
- printing, signage, promotional goods and other subcontractable supply;
- call-center/customer-care, events, training/e-learning;
- licensing/resale, hardware, AV, cloud and managed IT when partner/subcontract routes are feasible;
- unusual categories discovered empirically from the residual corpus.

## Historical priors

Use historical awards, bidder counts, buyer recurrence, supplier concentration, contract values, geography, and source/country evidence as priors for live ranking.

Historical ranking can operate without DCE when the question is market attractiveness. Historical DCE is not required merely to estimate category-level competition or buyer/supplier structure.

Do not let one noisy proxy dominate. Keep separate dimensions such as:

- lean feasibility;
- competition/ease proxy;
- expected-profit proxy;
- award-evidence coverage;
- buyer recurrence;
- likely partner/certification burden;
- live deadline and submission friction.

## Live scoring contract

Before DCE, score only preliminarily. A recommended scale is:

- `<70`: weak / low priority
- `70–79`: plausible
- `80–89`: strong preliminary candidate
- `90+`: forbidden until mandatory gates have been verified

A high historical prior never overrides a live mandatory gate.

## Selective DCE retrieval

Do not fetch DCE for the whole universe. Trigger DCE after preliminary ranking, strategic selection, or a configured score threshold.

Resolver statuses should remain explicit, including variants of:

- `DOWNLOADED_PUBLIC`
- `NO_PUBLIC_FILE` / `NO_PUBLIC_ATTACHMENTS_FOUND`
- `AUTH_REQUIRED`
- `CAPTCHA_REQUIRED`
- `INTEREST_RECORDING_REQUIRED`
- `TED_DOWNSTREAM_ADAPTER_PENDING`
- `TED_ROUTE_UNRESOLVED`
- `MANUAL_REQUIRED`
- `ERROR_RETRYABLE`
- `ERROR_HARD`

A portal adapter existing in code is not the same as live validation. Track route status separately from adapter existence.

For TED, resolve BT-15/document/submission URLs, classify the downstream portal, use a portal-specific public route where supported, and preserve unresolved downstream routes for later adapter expansion.

## Mandatory DCE gates

Before `FINAL_SUPER_GREEN`, extract and verify at least the gates that could invalidate SPM's bid, including when applicable:

- entity/geographic eligibility;
- required turnover/financial ratios;
- professional/technical references;
- mandatory certifications, manufacturer/reseller status, licenses or authorizations;
- minimum staffing, named CVs or experience thresholds;
- insurance/bond/guarantee requirements;
- subcontracting/consortium rules;
- exact deliverables and volumes;
- service levels, response times and location/on-site requirements;
- term, options and maximum value/quantity where relevant;
- award criteria and price weighting;
- mandatory forms/signatures/e-signature requirements;
- submission channel, deadline and language;
- IP/source-file/data-security constraints that affect AI/lean delivery.

Store the supporting text/snippet and source file for every decisive gate.

## Final classification

A final recommendation should distinguish:

- `FINAL_SUPER_GREEN`: mandatory gates verified; high expected attractiveness and feasible execution.
- `GREEN`: feasible/attractive but not exceptional.
- `YELLOW`: promising economics but unresolved or meaningful operational/eligibility risk.
- `RED`: clear blocker, poor economics, or incompatible requirements.
- `UNKNOWN/PENDING_DCE`: insufficient authoritative evidence.

Never upgrade UNKNOWN evidence to satisfied to make a candidate look greener.

## GitHub Actions execution guidance

Measured current production guidance for this repository:

- use up to **20 concurrent standard runners** when the workload/source tolerates it;
- on the measured DCE workload, approximately **2 candidates per shard** outperformed both low parallelism and one-candidate microsharding;
- allow a deeper matrix queue (up to the GitHub matrix limit used by the workflow) while capping active parallel runners;
- preserve `fail-fast: false` for independent shards;
- use bounded per-item retries with jitter and explicit timeout;
- detect and report 429/rate-limit signals rather than blindly increasing concurrency;
- avoid `cancel-in-progress` on harvest jobs where cancellation could discard unique work;
- avoid concurrent jobs pushing harvested datasets into Git history; persist harvest payloads as durable Release assets instead;
- keep Actions artifacts at zero for normal canonical DCE/discovery transport when Release-to-Release transport is available.

Re-benchmark when source mix changes. Measured settings are priors, not immutable laws.

## Adapter expansion strategy

When `TED_DOWNSTREAM_ADAPTER_PENDING` becomes the main bottleneck:

1. Audit pending domains by frequency.
2. Implement the highest-volume portal families first.
3. Prefer official/public document routes and deterministic vendor-family adapters over generic scraping.
4. A/B test on the **same candidate corpus** so retrieval uplift is measurable.
5. Reclassify each route as downloaded, public-but-empty, auth/CAPTCHA gated, unresolved, or retryable.
6. Persist every candidate pack and route resolution even when no DCE is downloaded.
7. Then attack the next frequency tier.

## Dedupe rules

Use exact canonical ID matching first. For cross-source mirrors, deterministic evidence may include official publication number, national procedure ID, ContractFolderID, buyer identity + exact reference, or explicit source linkage.

Do not use fuzzy title dedupe as a destructive filter for live opportunities. Similar generic titles can represent separate procurements.

## Working style for SPM

Favor execution and evidence over theory. When the user says “go/continue”, continue the highest-value unfinished pipeline step without re-asking already-known constraints.

Report concrete numbers:

- universe scanned;
- unique/current notices;
- candidates selected;
- DCE statuses;
- retrieval uplift after adapter changes;
- mandatory gates verified;
- final greens and blockers.

When a technical bottleneck is measured, solve the bottleneck rather than merely increasing compute.

## Current repository anchors

Read the live repository rather than relying on stale memory. Useful anchors include:

- warehouse registry under `tender_pipeline/`;
- `portal_routes.py`;
- `pipeline/ted_resolver.py`;
- current `pipeline/dce_worker_v*.py` and batch worker;
- discovery/materialization/aggregate scripts under `pipeline/`;
- `.github/workflows/` for production fanout/discovery;
- durable Releases named by discovery/DCE run IDs.

This skill defines operating invariants. Current counts, adapter coverage, run IDs, and opportunity rankings should be read from the latest registry, releases, and workflow outputs each time.
