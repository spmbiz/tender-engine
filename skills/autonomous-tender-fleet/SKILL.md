---
name: autonomous-tender-fleet
description: Operate the Tender Engine as a persistent self-healing CI fleet across GitHub Actions and CircleCI with durable state, transactional DCE leases, capacity management, retries, and GPT handoff.
---

# Autonomous Tender Fleet — Agent Skill V1

## Purpose

Operate the Tender Engine as a persistent, self-healing procurement fleet rather than a sequence of GPT-triggered one-off runs.

This skill is the authoritative operating contract for **orchestration, capacity management, durable state, provider fanout, retry/recovery, and GPT handoff**.

It complements `skills/supergreen-hunt/SKILL.md`, which remains authoritative for semantic tender screening, DCE reading, mandatory gates, and final GREEN / SUPER GREEN classification.

## Core principle

GPT sets intent and evaluates meaning. Deterministic workers continuously enumerate, retrieve, persist, dedupe, extract, and retry.

Do not require GPT to say `go`, `continue`, or `rerun` for routine harvesting once continuous mode is enabled.

Do not claim compute capacity is active merely because configuration exists. Report only observed or authenticated capacity.

# Sources of truth

Read these before changing fleet behavior:

- `control/desired_state.json` — persistent desired behavior.
- `control/provider_limits.json` — provider limits and verification status.
- `.github/workflows/autonomous-fleet.yml` — scheduler/controller entrypoint.
- `pipeline/fleet_controller_v3.py` — transactional orchestration logic.
- `.github/workflows/supergreen-discovery-v2.yml` — GitHub discovery fanout.
- `.github/workflows/dce-fanout-v2.yml` — DCE retrieval/extraction fanout.
- `.circleci/config.yml` — CircleCI compute pool.
- `pipeline/circleci_contracts_worker.py` — CircleCI source worker.
- `pipeline/circleci_aggregate.py` — CircleCI single-writer merge / DCE handoff.
- GitHub Release `fleet-state` — durable live controller state and GPT handoff.
- GitHub Releases `discovery-harvest-*` — canonical discovery packs.
- GitHub Releases `dce-harvest-*` — canonical DCE packs.

GitHub Actions artifacts are never the canonical store for valuable harvested data.

# Desired state contract

When `control/desired_state.json` has:

- `enabled=true`
- `continuous=true`

…the fleet should continue without GPT intervention.

`enabled=false` means stop launching new work while preserving durable state and already-persisted results.

`mode=maximum` means maximize **useful durable throughput**, not raw runner count. Respect source throttling, portal limitations, account concurrency, and write durability.

# Scheduler behavior

The autonomous controller currently runs on a short recurring GitHub Actions schedule and may also react to intentional trigger commits.

Each controller cycle must:

1. Load desired state and provider limits.
2. Load durable state from Release `fleet-state`.
3. Reconcile any pending transactional DCE lease.
4. Measure currently active/queued GitHub fleet work.
5. Allocate remaining capacity without oversubscription.
6. Prefer draining an existing durable discovery backlog before launching redundant discovery.
7. Launch new discovery only when due and capacity permits.
8. Trigger CircleCI only when enabled and due.
9. Persist state, health, metrics, and GPT handoff before exit.

A controller success means the control iteration completed; it does not imply every downstream harvest succeeded.

# GitHub capacity contract

Treat the configured GitHub hosted-runner concurrency limit as a hard budget.

Count other visible public repository jobs owned by the same operator when computing useful available capacity.

Subtract work planned earlier in the same controller cycle before deciding whether additional jobs can be launched.

Never intentionally oversubscribe the provider merely to create a large queue.

Current discovery architecture is designed around independent source work such as:

- TED
- sharded UK Contracts Finder publication windows
- sharded Ireland eTenders enumeration

DCE fanout should consume as many currently free GitHub slots as are useful, up to the configured cap, while browser-backed routes remain conservatively bounded inside each runner.

# CircleCI capacity contract

CircleCI is a second disposable compute pool, not a second source of truth.

The configured heavy fanout may use `parallelism: 30`, but it must remain gated until durable GitHub persistence is proven.

Mandatory CircleCI bridge secret:

`FLEET_GITHUB_TOKEN`

The token must allow the CircleCI fleet to persist canonical Release assets and perform the intended GitHub handoff operations. Never print or log the token.

`durable-bridge` must fail closed when the secret is absent.

Do **not** weaken this gate merely to make CircleCI appear green. A 30-worker run whose results cannot be durably recovered is worse than no run.

Once the bridge passes:

1. CircleCI workers process non-overlapping source shards.
2. Every shard persists its source pack to the workflow's canonical GitHub Release before success.
3. A single aggregator downloads the durable shard packs.
4. It performs deterministic merge/dedupe and builds wide-read packets.
5. It persists the canonical merged discovery pack.
6. It may hand a bounded candidate selection to the GitHub DCE workflow when the DCE lane is free.

Never let 30 Circle workers concurrently mutate a shared Git repository file.

# Transactional DCE lease contract

A DCE batch is **not processed when dispatched**.

Lifecycle:

`available -> leased/pending -> downstream workflow running -> success commit OR failure requeue`

A pending lease must contain enough immutable provenance to correlate it with the dispatched workflow, including the source discovery run and queue commit SHA.

On downstream success:

- commit the leased candidate identities into durable processed state;
- clear the lease.

On downstream failure/cancel/terminal non-success:

- clear the lease;
- return the candidates to the eligible queue automatically.

If no matching workflow appears before the configured lease timeout:

- expire the lease;
- return candidates to the queue.

Never permanently consume candidates merely because dispatch returned HTTP success.

# Canonical identity and scoring contract

The autonomous selector must dedupe using the same identity semantics enforced by the downstream DCE materializer/canonicalizer.

Do not use a weaker approximation that allows the downstream safety gate to rediscover duplicates.

Autonomous retrieval priority is a **prefetch/ranking score only**.

It must never claim the reserved final confidence range used by the post-DCE semantic gate. Preliminary autonomous score must remain below the final SUPER GREEN threshold.

`skills/supergreen-hunt/SKILL.md` controls final classification.

# Discovery backlog contract

A discovery harvest containing thousands of opportunities must not be considered consumed after one DCE batch.

Pin the active discovery run and drain it through successive bounded batches.

Only mark a discovery run processed/drained when no eligible unprocessed candidates remain above the configured retrieval threshold.

A failed DCE batch must not advance backlog completion.

Do not relaunch the same broad discovery every controller tick simply because capacity is available.

# Rate-limit and self-healing contract

Source-specific health beats naive parallelism.

For HTTP 429 / transient 5xx / network failures:

- respect `Retry-After` when present;
- use bounded exponential backoff;
- add source pacing when repeated throttling is observed;
- preserve partial durable progress;
- retry from a deterministic boundary where possible.

Do not respond to a source-side rate limit by blindly multiplying workers against that source.

Use spare capacity on other independent sources instead.

# Persistence contract

Before any valuable worker finishes, verify that the canonical output exists in durable storage.

Persist at minimum:

- source records / canonical merged records;
- discovery stats and provenance;
- DCE originals where retrieved;
- manifests and hashes;
- extracted corpora and gate evidence;
- queue provenance;
- controller state;
- health / metrics history;
- compact GPT handoff.

Temporary runner files, workspaces, and CI artifacts are disposable caches only.

# GPT handoff contract

When GPT returns to the project, do **not** restart harvesting from memory or from chat history.

First read the durable fleet handoff from Release `fleet-state`, especially:

- latest controller status;
- latest GPT summary;
- active discovery run;
- pending DCE lease;
- counts of processed candidates / drained runs;
- provider status and current bottleneck.

Then read only the new wide-read/deep-review material needed for semantic reasoning.

GPT owns:

- semantic wide read;
- unusual-opportunity detection;
- mandatory-clause interpretation;
- final gate resolution;
- delivery architecture;
- risk / bid strategy;
- final GREEN / SUPER GREEN classification.

Deterministic code owns repetitive enumeration, download, parsing, hashing, dedupe, extraction, routing, retries, and persistence.

# Provider truth / reporting contract

Distinguish these states explicitly:

- configured capacity;
- authenticated capacity;
- observed live capacity;
- currently active workers;
- queued workers;
- blocked/gated capacity.

Example: if CircleCI is configured for 30-way parallelism but `FLEET_GITHUB_TOKEN` is absent, report Circle as **configured but gated**, never as 30 active workers.

If provider-plan limits cannot be authenticated for this account/org, say they are unverified rather than copying a generic pricing-page number into live fleet state.

# Autoscaling objective

Optimize for marginal useful durable records per runner-minute, not theoretical concurrency.

Over time, maintain rolling source metrics such as:

- records enumerated;
- current/live unique records;
- duplicate rate;
- request failure rate;
- rate-limit events;
- wall-clock runtime;
- useful records per runner-minute;
- DCE success rate per portal;
- bytes/files durably persisted;
- retries / dead-letter counts.

A mature autoscaler may increase/decrease shards per source using these observed metrics, but must preserve all integrity and rate-limit rules above.

# User-intent shortcuts

Interpret common project commands as follows:

- `go`, `continue`, `suite` — inspect durable state first; advance the highest-value non-blocked next step. Do not restart completed work.
- `status`, `on en est où` — report durable controller/provider/backlog/DCE state, not chat-memory estimates.
- `cherche des greens / super greens` — use the latest durable discovery/DCE material and follow `skills/supergreen-hunt/SKILL.md`.
- `maximise / use all workers` — maximize useful provider capacity without oversubscription or source abuse.
- `rerun` — rerun only the failed/stale scope unless the user explicitly requests a fresh full harvest.

# Failure handling

On any failure, classify it before acting:

- transient source/network -> retry/backoff;
- authentication/secret -> fail closed and surface exact missing bridge;
- duplicate/canonicalization -> fix upstream identity and requeue;
- schema/validator -> fix producer contract and requeue;
- source route unsupported -> explicit route state and targeted research;
- CAPTCHA/MFA/login -> explicit gated state; never fabricate retrieval;
- provider capacity -> defer until capacity is available;
- durable-write failure -> worker must fail, never claim success.

# Stop condition

Continuous mode does not stop because one good tender was found.

A cycle may end when its allocated work is complete, but the persistent fleet remains enabled until desired state changes or a legitimate global blocker prevents further useful work.
