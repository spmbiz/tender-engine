# GitHub Actions Throughput Audit V2

Date: 2026-08-14

## Objective

Maximize safe public-runner throughput while minimizing GitHub Actions artifact storage, preserving every unique harvested procurement record/file durably, and preventing lost work or concurrent-write corruption.

## Preservation invariant

Actions artifacts are a temporary transport/debug mechanism, never the canonical data store.

Canonical harvested data is persisted as GitHub Release assets before a production worker is allowed to finish. DCE canonical packs preserve:

- original downloaded procurement files referenced by the resolver manifest;
- candidate metadata;
- resolver manifest and source URLs;
- SHA-256 inventory;
- extracted document index;
- full normalized text corpus;
- mandatory-gate snippets;
- batch retry/rate-limit metrics.

Recursive unpack copies are omitted from canonical storage only when they are exactly reconstructible from the preserved original downloaded archive.

## Before

Representative DCE run: `31838467001`.

- candidates: 33
- GitHub shard runners: 2
- local concurrency: 2 per shard
- wall time: 274 s (4m34s)
- throughput: 7.23 candidates/min
- Actions artifacts retained: 4
- Actions artifact bytes: 510,565,676 B
- storage pattern: shard output uploaded twice (once per shard, then again inside aggregate)
- retention: 7 days
- concurrency group: `cancel-in-progress: true`

## Benchmarks after architecture change

| Benchmark | Candidates | Shards | Max active runners | Wall time | Throughput | Downloaded public | Retries | Rate-limit signals | Actions artifacts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Before | 33 | 2 | 2 | 274 s | 7.23/min | n/a | n/a | n/a | 4 / 510.6 MB |
| 16-way | 33 | 17 | 16 | 230 s | 8.61/min | 31 | 2 | 0 | 0 |
| 20-way balanced | 33 | 20 | 20 | 152 s | **13.03/min** | 32 | 1 | 0 | 0 |
| 20-way micro-shards | 33 | 33 | 20 | 189 s | 10.48/min | 32 | 1 | 0 | 0 |

Measured winner on this browser-heavy 33-candidate workload: **20 active GitHub runners with roughly two candidates per shard**.

The 33 one-candidate micro-shard test was slower because runner/bootstrap overhead became material. The production planner therefore targets two candidates per shard while allowing a deeper queued matrix for larger workloads and keeping `max-parallel` independent at 20.

## Current production architecture

### DCE

`queue -> canonical dedupe -> browser/HTTP split -> dynamic matrix -> <=20 active runners -> bounded local concurrency -> extract -> gate snippets -> canonical Release persistence -> compact Release handoff -> deterministic single-writer aggregate`

Defaults:

- `MAX_DCE_JOBS=320`
- matrix depth up to 256 jobs
- `max-parallel=20`
- target 2 candidates/shard
- browser local concurrency 1
- HTTP local concurrency 4
- extraction workers 2
- gate workers 2
- one retry per candidate with jitter
- 150 s per-candidate timeout
- 429/rate-limit detection and reporting

### Discovery

`TED + Contracts Finder + 10 eTenders Ireland page-range runners -> durable Release source packs -> canonical merge -> wide-read packets -> durable consolidated Release`

Ireland is range-sharded. TED and Contracts Finder remain single jobs for their cursor/token chains until a non-overlapping partition scheme is proven.

## Storage changes

New production DCE and discovery workflows create **zero GitHub Actions artifacts**. Data moves through durable Release assets.

A 20-runner DCE benchmark measured:

- raw worker trees: ~403.9 MB
- compact extracted handoff: ~103.6 MB
- reduction before Release compression: ~74.35%
- Actions artifact retained storage: 0 B

Original procurement downloads remain in separate canonical Release packs and are not discarded.

## Integrity controls

- deterministic candidate-ID dedupe before fanout;
- shard-local output directories;
- no concurrent writes to a shared harvested file;
- no concurrent `git push` of harvested output;
- single-writer canonical aggregation;
- `fail-fast: false` for shard matrices;
- no `cancel-in-progress` on productive workflows;
- per-candidate retry metadata and explicit retryable statuses;
- Release upload presence verification before shard success;
- legacy Actions artifact deletion permitted only after durable migration verification.

## Startup optimization

- reuse preinstalled Chrome on `ubuntu-latest`;
- install Playwright only on browser-backed shards;
- no full Chromium install unless system Chrome is absent;
- run `apt-get update/install p7zip` only when `7z` is absent;
- keep HTTP-only shards free of Playwright;
- avoid one-candidate micro-shards when bootstrap overhead outweighs parallelism.

## Trigger hygiene

Production harvests are manual/specific-trigger driven. Legacy probes were moved to `workflow_dispatch` only. Benchmark and migration push triggers are scoped to exact files under `benchmarks/`; README or unrelated code edits do not intentionally fan out production runners.

## Bottleneck classification

### GITHUB HARD LIMIT

- standard concurrent runner ceiling for the account/plan is treated as 20 for this architecture;
- one matrix may contain at most 256 jobs, so planner depth is capped at 256.

### EXTERNAL SOURCE LIMIT

- eTenders Ireland sustained the tested 20-runner DCE load with **0 observed rate-limit signals**;
- 32/33 candidates downloaded in both 20-way tests;
- no measured evidence currently justifies reducing Ireland to 2, 4, or 5 runners.

### OUR WORKFLOW LIMIT — fixed

- `DCE_SHARDS=2`;
- `max-parallel=2`;
- `MAX_DCE_JOBS=80`;
- destructive `cancel-in-progress:true`;
- serial legacy portal probes;
- discovery Ireland in one browser job;
- redundant `needs:`/artifact transport architecture;
- legacy push triggers.

### OUR CODE LIMIT — mostly fixed

- local concurrency hardcoded at 2;
- no retry/rate-limit metrics;
- serial extraction and gate scanning;
- no queue candidate-ID dedupe;
- browser and HTTP work mixed in the same shards.

Remaining: partition TED/Contracts Finder into provably non-overlapping windows/cursors before increasing source-level job count.

### STORAGE LIMIT — fixed for new production

- old representative run consumed ~510.6 MB of retained Actions artifacts;
- new representative runs consume 0 B of Actions artifact storage;
- canonical harvested data is stored durably in Release assets instead.

### DATA INTEGRITY LIMIT — protected

Parallelism stops where writes cease to be independent. Aggregation is deliberately single-writer and deterministic. No lower concurrency cap is retained without a concrete source/integrity reason.

## Legacy artifact migration

An early cleanup attempt predated the preservation invariant and removed some reconstructible/duplicated intermediate artifacts before timing out. The large 33-candidate run remained represented by its final combined deep-review artifact, but duplication cannot be proven for every older legacy route artifact.

The replacement migration workflow is fail-safe:

`download old artifact -> compute SHA-256/size -> upload uniquely named Release asset -> verify remote asset -> only then delete Actions artifact -> persist migration index`.

Any failure before verification leaves the source Actions artifact untouched.
