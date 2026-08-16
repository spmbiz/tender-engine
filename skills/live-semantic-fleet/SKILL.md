---
name: live-semantic-fleet
description: Operate the Tender Engine as a backfill-once, delta-live semantic fleet using a persistent notice ledger, permissive Qwen 4B classification on parallel GitHub runners, GPT Web for high-value reasoning, SERP tools as secondary resolvers, and authoritative DCE gates for final decisions.
---

# Live Semantic Fleet — Tender Engine V2

Use this skill when designing, implementing, tuning, or operating the **live semantic classification layer** between broad official tender discovery and GPT Web / DCE deep review.

This skill is intentionally narrower than `skills/tender-engine/SKILL.md`. The canonical Tender Engine skill still owns procurement evidence, DCE requirements, durability and final bid/no-bid semantics. This skill defines the newer **high-throughput intelligence architecture** agreed for the live harvester.

## 1. Current operating reality

This project does **not** assume an OpenAI API agent architecture.

The actual control plane is:

```text
GPT Web / GPT-5.6 Sol
  -> reads GitHub + Drive state
  -> launches / edits / debugs workflows
  -> reviews high-value or ambiguous candidates

GitHub Actions / scripts
  -> bulk deterministic work
  -> local open-weight inference
  -> durable queues / ledgers / artifacts
```

Do not introduce an OpenAI API dependency unless explicitly requested.

GPT Web is the high-level orchestrator and semantic reviewer. GitHub-hosted workers are the scalable execution fleet.

## 2. V2 architecture decision: keep it simple

Do **not** implement a five-model cascade by default.

The preferred V1/V2 semantic architecture is:

```text
OFFICIAL LIVE SOURCES
        ↓
NORMALIZE + EXACT DEDUPE
        ↓
NOTICE INTELLIGENCE LEDGER
        ↓
NEW OR MATERIALLY CHANGED ONLY
        ↓
CHEAP DETERMINISTIC HARD FILTERS
        ↓
10–20 PARALLEL GITHUB WORKERS
EACH RUNNING QWEN ~4B
        ↓
PERSIST CLASSIFICATION
        ↓
GPT WEB
retained / unusual / uncertain / high-value
        ↓
DCE RETRIEVAL + AUTHORITATIVE GATES
        ↓
GREEN / FINAL SUPER GREEN
```

The key scaling insight is **not** to reclassify the whole active universe every pass.

The expensive problem is an initial backfill. The normal operating problem is a much smaller **NEW + UPDATED delta**.

## 3. Backfill once, then live delta forever

Treat these as two separate workloads.

### Initial backfill

The first production semantic pass may contain tens of thousands of still-active notices. That is acceptable even if it takes hours, because each stable notice is classified once and persisted.

Do not optimize architecture around making this one-time backfill instantaneous at the cost of complexity or recall.

### Live mode

After backfill, every live discovery pass must answer:

```text
Have we already seen this canonical notice?
  ├─ no  -> classify
  └─ yes -> has material content changed?
             ├─ no  -> SKIP LLM
             └─ yes -> reclassify
```

A live pass should spend semantic compute only on **new or meaningfully changed notices**.

This is the foundation of the system.

## 4. Notice Intelligence Ledger

Implement and preserve a durable ledger. At minimum store:

```text
source
source_notice_id
canonical_notice_id
canonical_url
first_seen_at
last_seen_at
publication_date
deadline
notice_hash
material_fields_hash
classifier_model
classifier_quant
classifier_prompt_version
classifier_version
classification
confidence
novelty_or_unusual_flag
classified_at
review_status
dce_status
needs_reclassification
```

### Identity

Use authoritative source notice IDs and deterministic cross-source linkage first. Do not destructive-fuzzy-dedupe procurement notices merely because titles are similar.

### Change detection

Do not requeue for irrelevant formatting or crawler metadata drift.

Requeue when material procurement meaning changes, including where applicable:

- title/scope;
- description;
- lot scope;
- deadline;
- estimated value;
- buyer/procedure identity;
- eligibility-related notice fields;
- document/DCE references;
- other fields known to change fit or feasibility.

Persist both `last_seen_at` and material hash so the engine can distinguish "still live" from "changed".

### Classifier-version behavior

Do not automatically reclassify the whole warehouse merely because a new prompt/model version exists. Re-backfill only when explicitly useful. New versions should apply to new/changed notices first, with targeted re-review of high-value historical candidates if desired.

## 5. Primary local model: Qwen ~4B on GitHub-hosted runners

The current preferred implementation target is a **Qwen 3/3.5-class ~4B instruct model**, quantized for CPU-friendly GGUF inference through `llama.cpp` or an equivalently robust local runtime.

This is a **deployment target to benchmark**, not a permanent vendor lock.

### Why 4B on GitHub

The fleet already uses many independent GitHub jobs. A matrix of 10–20 standard runners means 10–20 independent VMs, therefore up to 10–20 independent local-model instances processing shards simultaneously, subject to actual account concurrency and the repository's global capacity broker.

Prefer horizontal model parallelism across independent runners rather than forcing one home PC to be the primary inference bottleneck.

### Do not commit model weights to Git

Model weights belong in external model storage / release distribution and should be restored through a cache or downloaded when absent.

Treat:

```text
model/runtime cache = acceleration
classification ledger/results = durable business state
```

Never make the cache canonical.

### Amortize startup

Bad pattern:

```text
start VM
fetch model
classify 20 notices
exit
```

Preferred pattern:

```text
start VM
restore model/runtime cache
load model once
claim/process a substantial shard
persist outputs
exit
```

Measure separately:

- runner startup;
- cache restore/download;
- model load;
- inference time;
- persistence time.

## 6. Batching: not one prompt per tender by default

Do not assume `50,000 tenders = 50,000 model requests`.

The classifier should support compact multi-notice batches when empirical accuracy remains acceptable.

Candidate benchmark batch sizes:

```text
8
16
32
```

A batch contains compact notice summaries and returns one structured object per notice.

Do not increase batch size merely to claim throughput. Measure loss of attention, malformed output and false negatives.

### Compact model input

Prefer fields such as:

```text
notice_id
title
buyer
country
CPV/category
publication/deadline
estimated value if present
short description
compact lot summaries
important structured metadata
```

Do not feed full DCEs into Qwen 4B during initial semantic classification.

## 7. Classifier philosophy: high recall and permissive routing

The local classifier is **not a gatekeeper trying to maximize precision**.

Its first duty is to avoid losing unusual profitable opportunities.

Prompt doctrine:

```text
Optimize for recall.
Reject only when clearly and unambiguously outside plausible direct,
AI-assisted, software-enabled, subcontracted, brokered, resale,
creative, digital, operational or other lean-delivery capability.

If novel: KEEP or MAYBE.
If unusual: KEEP or MAYBE.
If information is insufficient: MAYBE / UNKNOWN.
If potentially subcontractable or brokerable: KEEP.
Do not reject merely because the opportunity is outside the current obvious niche list.
```

Recommended output shape:

```json
{
  "notice_id": "...",
  "decision": "STRONG_FIT|FIT|MAYBE|REJECT_OBVIOUS",
  "confidence": 0.0,
  "matched_capabilities": [],
  "possible_delivery_routes": [],
  "possible_blockers": [],
  "unusual_or_novel": false,
  "needs_gpt_review": false,
  "needs_dce": false,
  "reason": "short source-grounded explanation"
}
```

`REJECT_OBVIOUS` should be treated conservatively during rollout.

UNKNOWN is valid. The model must not invent eligibility, certifications, value, deadlines, buyer requirements, subcontract permissions or other procurement facts.

## 8. No tiny-model prefilter in the first production version

Earlier architecture considered a ~0.5–0.8B permissive garbage filter.

**Current decision: do not add it to V1 unless measurement proves Qwen 4B throughput is insufficient.**

Reasons:

- adds another runtime/model/prompt;
- adds another false-negative surface;
- complicates debugging and model-version state;
- the 10–20-way GitHub Qwen fleet may already have far more capacity than the live NEW/UPDATED arrival rate.

Use deterministic code for truly obvious exclusions before Qwen.

Only revisit a tiny-model tier if the measured live backlog demands it.

## 9. Do not over-engineer larger-model ensembles yet

Qwen 9B, GLM 9B, MiniCPM 8B, Phi, Mistral 24B and other open-weight models remain valid future benchmark candidates.

Do **not** make production depend on them yet.

Current rule:

```text
benchmark Qwen ~4B first
measure actual recall + throughput
only add complexity if a measured deficiency exists
```

Possible future upgrades:

- stronger local model on the user's private home runner for UNCERTAIN / HIGH-VALUE cases;
- alternate 3–4B model if Qwen is slower or less accurate on project data;
- disagreement review for only high-value borderline cases.

The classifier interface must therefore be model-agnostic even if Qwen 4B is the first implementation.

## 10. GPT Web boundary

GPT Web is not supposed to classify every raw notice forever.

Qwen handles repetitive semantic triage. GPT Web receives compact retained packets emphasizing:

- `STRONG_FIT`;
- `FIT`;
- important `MAYBE`;
- `unusual_or_novel=true`;
- high expected-value notices;
- low-confidence classifications;
- contradictions;
- candidates whose delivery route needs creative reasoning.

GPT Web should answer questions like:

- is this genuinely commercially attractive?;
- can we execute, broker, resell or subcontract this intelligently?;
- is there a non-obvious route to delivery?;
- should we fetch/read the DCE now?;
- what evidence is still missing?;

Persist GPT Web review labels so repeated semantic judgments can improve future prompts/rules/benchmarks.

## 11. DCE and final evidence boundary remains unchanged

No local model and no SERP result can bypass the canonical evidence rules.

No `FINAL_SUPER_GREEN` / 90+ final score without authoritative mandatory-gate evidence where required.

Qwen can prioritize DCE retrieval. It does not prove:

- eligibility;
- turnover/reference thresholds;
- mandatory certifications;
- exact subcontracting permission;
- contractual feasibility;
- final pricing;
- submission compliance.

Those remain authoritative-document questions.

## 12. OpenSERP / DDGS / SearXNG: secondary Search Fabric

Search engines are an **augmentation and resolver layer**, not the canonical tender source.

### Official procurement sources remain primary

TED, national portals, Contracts Finder, eTenders, SAM-like official sources and other authoritative feeds remain the live coverage backbone.

Do not replace source harvesting with Google/Bing SERPs.

### OpenSERP role

OpenSERP is useful for:

- exact tender title search;
- exact procurement/reference number search;
- buyer + reference resolution;
- discovering indexed public PDF/DOCX/XLS attachments;
- finding mirrored official notice pages;
- locating award notices or related authoritative pages;
- recovering document routes when a portal landing page is awkward;
- search-based gap filling around unresolved DCE candidates.

Treat CAPTCHA / throttling / 503 / incomplete results as explicit non-success states. SERP absence never proves that a document or tender does not exist.

### DDGS role

Use DDGS as a lightweight Python/HTTP search adapter or fallback when it is operationally cheaper than a persistent service.

It is particularly attractive for short-lived workers because it can be embedded directly in Python without standing up a heavy service.

### SearXNG role

SearXNG is optional for a persistent private/home search service where multi-engine aggregation and warm local state are valuable.

Do not make the live Tender Engine depend on the user's PC being online.

### Normalized Search Fabric contract

Where practical expose one internal search adapter contract:

```text
query
engine/provider
region/language
result_rank
title
url
snippet
retrieved_at
status
error/captcha/throttle state
```

Then dedupe/merge and measure actual downstream yield.

## 13. Search yield measurement

Do not assume one search engine is always best.

Track by query family and resolver use case:

```text
queries
successful responses
captcha/throttle/errors
new useful URLs
new DCE/document URLs
authoritative matches
resolved candidates
compute/wall time
```

Examples of query families:

```text
"exact title"
"exact reference"
"buyer + reference"
site:official-domain
filetype:pdf
filetype:docx
award + reference
```

Promote the engines/query families that actually resolve procurement evidence.

## 14. Home PC: optional bonus lane, never a required production dependency

The user's Windows PC may later run persistent tools such as:

- OpenSERP;
- SearXNG/DDGS;
- `llama.cpp`;
- a stronger local model;
- Playwright/browser resolution;
- warm caches.

But the Tender Engine must continue when the PC is off.

### Security rule: no self-hosted runner from a public repo

This repository is public. Do not execute arbitrary repository workflow code directly on the user's personal self-hosted Windows runner.

Preferred pattern:

```text
PUBLIC tender-engine
       ↓ durable queue/state
PRIVATE CONTROL REPO
       ↓ self-hosted runner
USER PC
```

If a personal runner is used, it should belong to a private control plane with tightly scoped workflows. Public repo PR/fork code must never have a path to arbitrary execution on that machine.

The PC can later act as an opportunistic stronger-review lane. It must not be required for basic live classification.

## 15. Fleet and capacity behavior

Do not assume every workflow owns all GitHub concurrency.

Respect the repository/account global capacity broker and currently active sibling workloads.

For semantic classification:

- use independent shards;
- `fail-fast: false` where appropriate;
- every worker writes isolated outputs;
- canonical aggregation is single-writer / transaction-safe;
- model failure returns explicit state and does not consume/lose notice identity;
- workers checkpoint/persist before exit;
- re-running a shard is idempotent.

Prefer work stealing / queue claims when it materially improves utilization, but do not rewrite the entire fleet merely for theoretical elegance.

## 16. Required benchmark before autonomous rejection

Before trusting Qwen 4B for destructive filtering, benchmark on real project data.

Use at least several hundred previously reviewed notices, preferably 500–1,000+ spanning:

- obvious non-fit;
- obvious fit;
- misleading keyword matches;
- unusual profitable opportunities;
- subcontract/broker/resale routes;
- borderline cases;
- known GREEN / SUPER-GREEN-like examples.

Metrics:

```text
recall on known good opportunities          CRITICAL
false-negative rate on unusual good cases  CRITICAL
precision on retained candidates
REJECT_OBVIOUS precision
MAYBE rate
JSON/schema validity
notices/minute per runner
20-worker aggregate throughput
model/cache startup overhead
peak RAM
wall time
```

The key capacity comparison is:

```text
NEW + UPDATED NOTICES / HOUR
versus
QWEN FLEET CLASSIFICATION CAPACITY / HOUR
```

If fleet capacity is comfortably above live arrival rate, do not add more model tiers.

## 17. Rollout sequence

Implement in this order unless measured repository state dictates otherwise:

1. **Notice Intelligence Ledger** with canonical identity and material change hash.
2. **NEW/CHANGED queue** so unchanged notices skip semantic work.
3. **Qwen 4B single-runner smoke** with strict structured output.
4. **Real benchmark corpus** and recall/throughput measurement.
5. **Qwen model/runtime caching**.
6. **10–20 runner matrix/fleet integration** respecting global capacity.
7. **Shadow classification** on live candidates; no destructive auto-reject.
8. **Persist Qwen classifications** with model/prompt/version provenance.
9. **GPT Web compact retained handoff**.
10. **SERP Search Fabric adapters** for unresolved DCE/reference resolution.
11. Only after measurement: enable safe automatic treatment of `REJECT_OBVIOUS` if false-negative risk is acceptably low.
12. Only after measurement: consider stronger PC model, alternate open model, or tiny prefilter.

## 18. Do not confuse volume metrics

The backfill size is not the normal daily semantic workload.

Always report separately:

```text
ACTIVE UNIVERSE
BACKFILL REMAINING
DISCOVERED THIS PASS
NEW UNSEEN
MATERIALLY UPDATED
UNCHANGED SKIPPED
QWEN CLASSIFIED
QWEN BACKLOG
GPT REVIEW QUEUE
DCE QUEUE
```

The important live-health KPI is not "50k active tenders". It is:

```text
new_or_updated_arrival_rate
classifier_capacity
oldest_backlog_age
```

## 19. Success condition

The intended steady state is:

```text
worldwide official sources continuously harvested
        ↓
all active notice identities remembered
        ↓
unchanged notices cost zero LLM inference
        ↓
new/changed notices rapidly classified by parallel Qwen workers
        ↓
GPT Web sees only commercially plausible / unusual / uncertain opportunities
        ↓
DCE evidence resolves mandatory gates
        ↓
valuable opportunities persist and never need to be rediscovered from scratch
```

The goal is **continuous coverage with bounded semantic work**, not an ever-growing reprocessing loop.

## 20. Non-negotiable summary

```text
BACKFILL ONCE; PROCESS DELTAS FOREVER.
LEDGER BEFORE LLM SCALE.
QWEN ~4B ON PARALLEL GITHUB RUNNERS FIRST.
NO TINY-MODEL TIER UNTIL A MEASURED NEED EXISTS.
HIGH RECALL > AGGRESSIVE EARLY PRECISION.
NOVEL / WEIRD / UNKNOWN SURVIVES.
GPT WEB OWNS HIGH-VALUE CREATIVE REASONING.
OFFICIAL SOURCES OWN DISCOVERY COMPLETENESS.
SERP IS A RESOLVER / GAP-FILLER, NOT SOURCE OF TRUTH.
DCE OWNS FINAL MANDATORY GATES.
NO PERSONAL SELF-HOSTED RUNNER DIRECTLY FROM PUBLIC REPO WORKFLOWS.
MEASURE LIVE NEW+UPDATED/HOUR AGAINST QWEN CAPACITY/HOUR.
DO NOT ADD ARCHITECTURAL COMPLEXITY WITHOUT A MEASURED BOTTLENECK.
```