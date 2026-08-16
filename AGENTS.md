# AGENTS.md — Tender Harvester Agent Contract

## Read first

Before modifying discovery, semantic classification, DCE routing, or fleet architecture, read:

1. `skills/tender-engine/SKILL.md` for canonical procurement evidence and final bid/no-bid rules;
2. `skills/live-semantic-fleet/SKILL.md` for the **current V2 backfill-once + live-delta + Qwen architecture**;
3. `docs/HARVESTER_SCALE_BLUEPRINT.md` plus the existing Super Green/autonomous-fleet docs for broader scaling and durability rules.

Where older local-LLM ideas conflict with `skills/live-semantic-fleet/SKILL.md`, the newer skill wins. In particular, the current first implementation target is **Qwen ~4B on parallel GitHub-hosted runners after a persistent Notice Intelligence Ledger**, with no mandatory sub-1B prefilter or multi-model ensemble unless measurement later proves it necessary.

## Real operating environment

This project does **not** assume OpenAI API agents. The high-level controller is ChatGPT Web (currently GPT-5.6 Sol in the user's workflow) using native GitHub and Google Drive connectivity to launch, inspect, edit, debug and steer work. GitHub Actions / scripts provide bulk execution.

Do not introduce an OpenAI API dependency unless the user explicitly requests one.

## Current target architecture

```text
broad official discovery
  -> normalize / exact dedupe
  -> Notice Intelligence Ledger
  -> new or materially changed only
  -> cheap deterministic hard filters
  -> parallel Qwen ~4B GitHub workers
  -> persist classification + model/prompt provenance
  -> GPT Web for retained / unusual / uncertain / high-value cases
  -> DCE retrieval / authoritative gate extraction
  -> final GREEN / SUPER GREEN
```

The key scaling rule is **BACKFILL ONCE; PROCESS DELTAS FOREVER**. An active notice that is already known, unchanged, and classified should cost zero repeated LLM inference.

## Qwen role

Use a Qwen 3/3.5-class ~4B instruct GGUF as the first benchmark target on standard GitHub-hosted runners. A 10–20 job matrix can provide 10–20 independent model instances in parallel, subject to real account/global fleet capacity.

Do not commit weights to Git. Cache pinned model/runtime artifacts, load once per worker, process substantial shards, persist isolated outputs, and aggregate transaction-safely.

Support compact batching where benchmarked safe. Do not assume one prompt per tender.

## Recall doctrine

The local classifier is a high-recall semantic router, not the final commercial/legal authority.

Reject only clearly irrelevant opportunities. Novel, unusual, potentially brokerable, subcontractable, AI-assisted, software-enabled, resale, creative, digital or otherwise plausibly lean-deliverable opportunities should survive for review. Insufficient evidence remains `MAYBE` / `UNKNOWN` rather than becoming rejection.

Never invent eligibility, value, certifications, buyer requirements, deadlines, subcontract permissions or DCE facts.

## No over-engineering by default

Do not add a 0.5–0.8B prefilter, Qwen9B, GLM, MiniCPM, Mistral, voting ensembles, or other model tiers before the Qwen4B benchmark demonstrates a real throughput/recall problem.

Keep interfaces model-agnostic so alternatives can be tested later.

## SERP / Search Fabric

Official procurement sources remain primary for completeness and source truth.

OpenSERP, DDGS and optional SearXNG are secondary resolution/gap-filling tools for:

- exact title/reference search;
- buyer + reference resolution;
- public PDF/DOCX/XLS discovery;
- mirrored official notice pages;
- award/related page discovery;
- unresolved DCE/document routes.

SERP absence never proves a tender/document does not exist. CAPTCHA, throttle and errors must remain explicit.

## GPT Web boundary

GPT Web should focus on commercially plausible, unusual, uncertain, contradictory or high-value candidates and on creative delivery/broker/subcontract reasoning. Persist those decisions as reusable labels.

GPT Web is not the daemon that reclassifies the entire world every live pass.

## DCE boundary

No local model and no SERP output may bypass authoritative mandatory-gate verification. No FINAL SUPER GREEN / 90+ without the evidence required by `skills/tender-engine/SKILL.md`.

## Security

This repository is public. Do not route arbitrary public-repo workflow execution to the user's personal self-hosted PC. If the PC is used for OpenSERP, a stronger model, browser work or warm caches, it should be behind a **private control repository**. Public PR/fork code must never have arbitrary execution access to the machine.

The live system must continue when the PC is offline.

## Core philosophy

1. Official sources for coverage.
2. Deterministic facts in code.
3. Persistent ledger before LLM scale.
4. Qwen ~4B on parallel GitHub workers for semantic triage.
5. High recall: weird/novel/unknown survives.
6. GPT Web for high-value hard cases.
7. DCE for final mandatory gates.
8. OpenSERP/DDGS/SearXNG as resolver tools, not source-of-truth replacements.
9. Measure NEW+UPDATED/hour versus classifier capacity/hour.
10. Do not add architectural complexity without a measured bottleneck.
