# Public Tender Intelligence — Lean Procurement Engine v2

This repository contains the live tender discovery, procurement-document retrieval, and DCE-aware qualification workbench.

## Core flow

`broad official discovery -> normalize/dedupe -> GPT wide read -> DCE candidate queue -> portal resolver -> DCE download -> recursive extraction -> manifest + SHA-256 -> mandatory-gate deep read -> final rescore`

## Super Green operating sources

- `skills/supergreen-hunt/SKILL.md` — authoritative GPT/agent operating contract. GPT-wide-read and DCE-final-gate rules live here.
- `docs/SUPERGREEN_SYSTEM_V2.md` — implemented architecture, executors, handoffs and measured benchmarks.
- `docs/SUPERGREEN_HUNT_RUNBOOK.md` — reproducible runbook capturing the process used to surface and verify fresh opportunities such as Barnagh.
- `docs/PARALLELIZATION_AUDIT.md` — performance audit and optimization rationale.
- `DCE_ROUTE_MATRIX.md` — procurement portal route/status matrix.
- `portal_routes.py` — machine-readable portal registry.

## Integrity rules

- No fabricated eligibility facts.
- UNKNOWN stays UNKNOWN.
- Login/MFA/CAPTCHA barriers return explicit non-success states.
- Canonical dedupe/freshness must happen before expensive verification, but unusual live tenders are not hidden from GPT merely by keyword filters.
- **GPT materially reads the broad generated live pool before the DCE shortlist is finalized.**
- **No FINAL SUPER GREEN score (90+) without verified mandatory gates from the DCE/RFQ/RFT or equivalent authoritative procurement pack.**

## Implemented V2

Discovery:

`TED + Contracts Finder + eTenders Ireland -> canonical merge -> seen_before -> GPT wide-read packets`

DCE pipeline:

`GPT selections -> queue -> two GitHub shards -> bounded local concurrency -> TED BT-15/downstream adapter -> download -> recursive archive extraction -> corpus -> gate snippets -> GPT full DCE read`

Key workflows:

- `.github/workflows/supergreen-discovery-v2.yml`
- `.github/workflows/dce-fanout-v2.yml`

Key executors live under `pipeline/`.
