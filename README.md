# Public Tender Intelligence — Lean Procurement Engine v2

This repository contains the live tender discovery, procurement-document retrieval, and DCE-aware qualification workbench.

## Core flow

`broad official discovery -> normalize/dedupe -> GPT wide read -> DCE candidate queue -> dynamic portal-aware fanout -> DCE download -> recursive extraction -> manifest + SHA-256 -> mandatory-gate deep read -> final rescore`

## Storage contract

**GitHub Actions artifacts are not the canonical data store.**

Valuable harvested data is persisted durably before a worker is allowed to finish:

- discovery source packs -> GitHub Release assets;
- original downloaded DCE/RFQ/RFT files -> per-candidate GitHub Release assets;
- candidate metadata, manifests, SHA-256 inventory, corpus and gate snippets -> same canonical candidate pack;
- consolidated deep-review outputs -> final Release assets.

Recursive unpack copies are not duplicated durably when they can be reconstructed exactly from the preserved original archive. Unique harvested source files are never deleted merely to reduce Actions artifact storage.

## High-throughput execution

DCE fanout:

`queue -> deterministic dedupe -> browser/HTTP split -> up to 20 independent shards -> bounded local worker concurrency -> durable Release persistence -> compact handoff -> atomic canonical aggregate`

Current defaults permit up to 20 GitHub-hosted shard runners when the queue and account-wide concurrency allow it. Browser work stays conservative inside each runner while HTTP-only shards can use higher local concurrency.

Discovery fanout:

`TED + Contracts Finder + 10 eTenders Ireland page-range shards -> durable source packs -> canonical merge/dedupe -> GPT wide-read packets`

The workflows reuse the preinstalled Chrome on `ubuntu-latest` and install Playwright only on browser-backed shards. Legacy/debug probes are manual-only.

## Super Green operating sources

- `skills/supergreen-hunt/SKILL.md` — authoritative GPT/agent operating contract. GPT-wide-read and DCE-final-gate rules live here.
- `docs/SUPERGREEN_SYSTEM_V2.md` — implemented architecture, executors, handoffs and measured benchmarks.
- `docs/SUPERGREEN_HUNT_RUNBOOK.md` — reproducible runbook capturing the process used to surface and verify fresh opportunities such as Barnagh.
- `docs/PARALLELIZATION_AUDIT.md` — original performance audit and optimization rationale.
- `DCE_ROUTE_MATRIX.md` — procurement portal route/status matrix.
- `portal_routes.py` — machine-readable portal registry.

## Integrity rules

- No fabricated eligibility facts.
- UNKNOWN stays UNKNOWN.
- Login/MFA/CAPTCHA barriers return explicit non-success states.
- Canonical dedupe/freshness happens before expensive verification.
- Every shard owns independent output paths; workers never concurrently mutate one shared output file.
- Aggregation/deduplication is deterministic and single-writer.
- Production workers do not concurrently `git push` harvested data.
- A durable Release upload is verified before the worker is considered successful.
- **GPT materially reads the broad generated live pool before the DCE shortlist is finalized.**
- **No FINAL SUPER GREEN score (90+) without verified mandatory gates from the DCE/RFQ/RFT or equivalent authoritative procurement pack.**

## Key workflows

Production:

- `.github/workflows/supergreen-discovery-v2.yml`
- `.github/workflows/dce-fanout-v2.yml`

Preservation/maintenance:

- `.github/workflows/migrate-actions-artifacts.yml` — verify-before-delete migration from legacy Actions artifacts into durable Release assets.
- `.github/workflows/artifact-gc.yml` — inventory-only; it does not delete harvested data.

Legacy probes are `workflow_dispatch` only.

Key executors live under `pipeline/`.
