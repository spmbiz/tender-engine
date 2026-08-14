# Public Tender Intelligence — Lean Procurement Engine v1.9

This repository contains the live tender discovery, procurement-document retrieval, and DCE-aware qualification workbench.

## Core flow

`notice -> normalize/dedupe -> preliminary screen -> official document route -> DCE download -> recursive extraction -> manifest + SHA-256 -> mandatory-gate analysis -> delivery-fit analysis -> final rescore`

## Super Green operating sources

- `skills/supergreen-hunt/SKILL.md` — authoritative GPT/agent operating contract for fresh DCE-aware tender hunts.
- `docs/SUPERGREEN_HUNT_RUNBOOK.md` — reproducible runbook capturing the process used to surface and verify fresh opportunities such as Barnagh.
- `docs/PARALLELIZATION_AUDIT.md` — performance audit and v2 architecture for parallelizing discovery, DCE retrieval, extraction, and GPT qualification.
- `DCE_ROUTE_MATRIX.md` — procurement portal route/status matrix.
- `portal_routes.py` — machine-readable portal registry.

## Integrity rules

- No fabricated eligibility facts.
- UNKNOWN stays UNKNOWN.
- Login/MFA/CAPTCHA barriers return explicit non-success states.
- Canonical dedupe/freshness must happen before expensive verification.
- **No FINAL SUPER GREEN score (90+) without verified mandatory gates from the DCE/RFQ/RFT or equivalent authoritative procurement pack.**

## Current architectural direction

The existing scripts have validated real portal routes. The next optimization step is to replace hardcoded one-off probes with a queue-driven, matrix-parallel pipeline:

`parallel discovery -> normalize/dedupe -> cheap score -> candidate queue -> parallel portal workers -> extraction -> gate evidence -> parallel GPT qualification -> MASTER/evidence persistence`
