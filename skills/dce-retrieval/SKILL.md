---
name: dce-retrieval
description: Resolve, download, preserve, unpack, extract, and hand off public tender DCE/procurement packs at high parallelism using the Tender Engine portal-adapter fleet.
---

# DCE Retrieval — Specialist Agent Skill V1

## Purpose

Operate only the authoritative-document retrieval lane of the Tender Engine: turn a queue of selected live opportunities into durably preserved DCE/procurement packs, extracted corpora, gate evidence, and a compact GPT deep-review handoff.

This skill is authoritative for DCE routing/retrieval/extraction mechanics. Semantic selection and final GREEN/SUPER GREEN classification remain governed by `skills/supergreen-hunt/SKILL.md`; persistent capacity/orchestration remains governed by `skills/autonomous-tender-fleet/SKILL.md`; canonical evidence/preservation invariants remain governed by `skills/tender-engine/SKILL.md`.

## Core contract

Input:

- canonical candidate identity;
- source/portal;
- notice URL and route identifiers;
- source discovery run provenance;
- queue status eligible for DCE retrieval.

Output per candidate:

- explicit retrieval status;
- original authoritative files when publicly obtainable;
- SHA-256/size/source URL manifest;
- recursive unpacked/extracted document index;
- full text corpus where extractable;
- mandatory-gate evidence snippets;
- durable canonical Release pack;
- compact handoff for GPT deep read.

Never fabricate a document, URL, gate, or successful retrieval.

## Retrieval statuses

Use explicit states, including:

- `DOWNLOADED_PUBLIC`
- `NO_PUBLIC_FILE`
- `NO_PUBLIC_ATTACHMENTS_FOUND`
- `AUTH_REQUIRED`
- `CAPTCHA_REQUIRED`
- `INTEREST_RECORDING_REQUIRED`
- `TED_DOWNSTREAM_ADAPTER_PENDING`
- `TED_ROUTE_UNRESOLVED`
- `MANUAL_REQUIRED`
- `ERROR_RETRYABLE`
- `ERROR_HARD`

An adapter existing in code is not evidence that a specific candidate downloaded successfully.

## Route resolution

1. Start from canonical notice/ref; never guess a document URL from title alone.
2. Prefer official/public deterministic document routes over generic browser scraping.
3. For TED, resolve BT-15/document URLs and classify the downstream portal before retrieval.
4. Reuse known portal/vendor adapters from `portal_routes.py`, `pipeline/ted_resolver.py`, and current `pipeline/dce_worker_v*.py` / `pipeline/dce_worker.py`.
5. Before declaring an unsupported downstream route, preserve its hostname, URL, candidate identity, and failure state for frequency-based adapter expansion.
6. Never bypass login, MFA, CAPTCHA, controlled attachments, or portal access restrictions.

## Parallelism contract

The current production prior is:

- GitHub hosted-runner budget: up to 20 standard concurrent runners when actually free;
- DCE matrix queue: up to 256 shards;
- preferred measured target: ~2 candidates per shard;
- browser-backed shards: conservative local concurrency, normally 1;
- direct HTTP shards: higher bounded local concurrency, currently 4;
- `fail-fast: false` across independent shards;
- extraction and gate-snippet stages may use per-candidate worker pools.

Do not hardcode two global shards. Let `pipeline/build_dce_shards.py` compute the matrix from queue size, portal class, available max parallelism, and shard target.

More runners are not automatically better. On 429/throttling or portal instability, reduce concurrency for that portal while using spare capacity on independent sources/routes.

## Canonical execution path

Use the current production workflow:

`.github/workflows/dce-fanout-v2.yml`

Typical inputs:

- `selection_path`
- `source_discovery_run`
- `max_jobs`
- `max_parallel`
- `max_shards`
- `jobs_per_shard`

The workflow should:

1. Materialize the exact selected queue from the durable discovery Release.
2. Persist queue + selection provenance before retrieval starts.
3. Build browser/HTTP-aware shards with `pipeline/build_dce_shards.py`.
4. Resolve/download with `pipeline/dce_batch_worker.py` + portal adapters.
5. Recursively unpack/extract with `pipeline/extract_corpus.py`.
6. Extract gate evidence with `pipeline/extract_gates.py`.
7. Build per-candidate durable packs with `pipeline/durable_dce_pack.py`.
8. Build compact handoffs with `pipeline/slim_dce_output.py`.
9. Upload/verify every shard pack to the canonical `dce-harvest-<run_id>` GitHub Release.
10. Aggregate compact handoffs with `pipeline/aggregate_dce.py` and persist the consolidated deep-review pack.

## Persistence contract

GitHub Actions artifacts are disposable transport/debug only. Valuable DCE work is successful only after durable Release persistence is verified.

Persist, as applicable:

- exact candidate/selection provenance;
- original public archive/files;
- manifest with hashes;
- canonical document index;
- compact corpus/evidence;
- gate snippets;
- retrieval route/status;
- aggregate deep-review queue/summary.

Do not delete unique procurement data to save artifact space.

## Extraction contract

Recursively materialize supported archives and office/document formats. Preserve the original archive even when derived files can be reconstructed.

Gate snippets are retrieval aids, not semantic verdicts. A zero hit for `turnover` does not prove there is no turnover requirement; GPT must inspect the authoritative corpus before final eligibility.

## Retry and rate-limit contract

For transient network/5xx/429 failures:

- bounded retries only;
- jitter/backoff;
- respect `Retry-After` when available;
- preserve partial successful candidates;
- never repeat completed candidates merely because siblings failed.

Auth/CAPTCHA/MFA are not retry storms: classify and move on.

## Transactional fleet behavior

When invoked by the autonomous fleet, a DCE batch is leased, not consumed at dispatch time.

Only commit candidate IDs to processed state after the downstream DCE workflow completes successfully. On failure/cancel/lease timeout, return the batch to the eligible queue.

Do not launch a duplicate DCE workflow while the DCE lane already has an active leased batch unless explicitly operating an independent manually scoped queue.

## Adapter expansion

When retrieval success is limited by unsupported downstream portals:

1. rank unresolved domains by candidate frequency/value;
2. research/implement the highest-yield official/public route once;
3. A/B test on the same candidate set;
4. measure uplift in `DOWNLOADED_PUBLIC`;
5. preserve explicit gated/no-file results;
6. register the validated route so future agents do not repeat research.

## GPT handoff

This skill stops at authoritative materialization and compact evidence handoff.

GPT deep review must receive enough material to inspect the full DCE, not only snippets, and must resolve mandatory gates under `skills/supergreen-hunt/SKILL.md`.

## Reporting

Report exact measured counts:

- candidates queued;
- shards planned / max parallel;
- portal distribution;
- downloaded public;
- auth/CAPTCHA/interest gates;
- retryable/hard failures;
- original files/bytes persisted;
- fully extracted candidates;
- deep-review candidates;
- wall time and retrieval success by portal when available.

Never call configured capacity active capacity unless observed.
