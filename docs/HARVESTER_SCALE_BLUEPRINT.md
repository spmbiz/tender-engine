# Tender Harvester Scale Blueprint

## Operating context

This project is **not built around OpenAI API agents**. The high-level orchestrator is ChatGPT Web (currently GPT-5.6 Sol in the user's workflow) with native GitHub and Google Drive connectivity. GitHub Actions / CircleCI / scripts are disposable compute and execution surfaces; ChatGPT Web is the launcher, editor, debugger, reviewer and strategic controller.

Do not redesign this repository assuming persistent OpenAI API access. Prefer durable queues, compact machine-readable handoffs, reproducible executors, logs, manifests, checkpoints and review artifacts that ChatGPT Web can inspect and steer through native connectors.

## North-star objective

Do not optimize for number of notices. Optimize toward:

```text
Expected Tender Value per compute hour
= P(eligible)
× P(can_deliver_or_broker)
× P(win)
× expected gross margin
```

Before enough outcome data exists, preserve the features needed to improve these probabilities later.

## Common architecture

```text
OFFICIAL SOURCE ADAPTERS
  -> RAW NOTICE STORE
  -> NORMALIZATION / DEDUPE
  -> CHEAP HARD FILTERS
  -> EMBEDDING / SEMANTIC PREFILTER (optional)
  -> LOCAL SMALL-LLM TRIAGE
  -> GPT WEB WIDE READ FOR VALUABLE / AMBIGUOUS ITEMS
  -> SPECULATIVE DCE QUEUE
  -> PORTAL-AWARE DCE RETRIEVAL
  -> EXTRACTION / MANIFEST / HASHING
  -> AUTHORITATIVE MANDATORY-GATE REVIEW
  -> GREEN / SUPER GREEN
  -> OUTCOME FEEDBACK
```

The pipeline should separate **discovery**, **retrieval**, and **reasoning** into independent always-fed queues.

## 1. Discovery and intelligence must be separate

Discovery workers should maximize official-source coverage cheaply using APIs, feeds, pagination and stable portal routes. They should not require frontier-model reasoning.

Intelligence workers consume normalized candidates only after cheap filtering.

Target conceptual funnel:

```text
very large raw pool
-> deterministic deadline/source/category/CPV filters
-> semantic similarity / keyword expansion
-> small local model
-> GPT Web review on the surviving high-value/uncertain subset
-> DCE verification
```

Exact retention rates must be measured, not invented.

## 2. Replace universal expensive semantic read with a cascade

The existing GPT wide-read role should progressively become a **high-value review layer**, not the first semantic filter over obvious garbage.

Before GPT Web, apply:

- deadline validity;
- geographic constraints that are genuinely known;
- hard exclusion categories;
- CPV/category rules;
- positive/negative phrase families;
- optional embedding similarity;
- optional local 3B–4B semantic classifier.

Preserve recall aggressively: false negatives on genuine GREEN/SUPER-GREEN-like opportunities are more dangerous than allowing some false positives through.

## 3. Embedding/similarity prefilter

Add an optional cheap semantic stage using canonical examples of desirable scopes:

```text
website redesign / CMS / web platform
digital portal / lightweight software
AI automation / data-processing implementation
transcription / language-processing
graphic design / creative services
video / media production
printing / print brokerage / fulfillment
```

Use similarity only as a ranking/filtering aid. Never infer eligibility or contractual facts from embedding distance.

Maintain a positive corpus and a negative corpus of previously reviewed tenders.

## 4. Negative corpus

Persist explicit rejection reasons and representative text for common non-fit categories, e.g.:

```text
civil works
road works
medical supplies
fuel
vehicles
heavy industrial equipment
cleaning
catering
unrelated maintenance
other historically poor-fit categories
```

Do not hard-code broad categories forever if evidence later shows profitable subcases. Rejection logic should be measurable and reversible.

## 5. Always-on speculative DCE retrieval

Do not wait for final GPT review before beginning every DCE download.

When a candidate clears a safe plausibility threshold and the authoritative pack is cheaply retrievable, enqueue speculative retrieval early.

```text
candidate plausibly fits
-> DCE queue immediately
-> retrieval/extraction runs in parallel with semantic review
```

Storage and bandwidth are usually cheaper than human/GPT idle time caused by serial retrieval.

Speculative retrieval must never imply the tender is GREEN.

## 6. Three independent pipelines

Operate continuously as:

```text
DISCOVERY PIPELINE
produces normalized candidate backlog

DCE RETRIEVAL PIPELINE
consumes plausible candidates and produces verified source packs

REVIEW PIPELINE
consumes notices / extracted DCE packs and produces decisions
```

A slow portal should not stall source discovery. A long GPT review should not stall DCE downloads.

## 7. Portal adapter architecture

Push `portal_routes.py` / route matrix concepts toward explicit adapters with stable contracts:

```text
search()
normalize_notice()
next_page_or_cursor()
extract_document_links()
download_documents()
auth_state()
retry_policy()
rate_limit_policy()
```

Examples: TED, Contracts Finder, eTenders, PLACE-like portals, SAM-like portals and other official procurement systems.

Every adapter should return explicit failure states rather than silently dropping candidates.

## 8. Shared fetch/content cache

Add a reusable cache ledger for notices, landing pages and procurement files:

```text
url
canonical_url
status
etag
last_modified
content_hash
fetched_at
content_type
source_adapter
```

For documents also preserve:

```text
sha256
original_filename
size
manifest_path
candidate_id
```

Canonical procurement evidence remains in the repository's durable Release/source-pack system. CI cache is only an acceleration layer.

## 9. Incremental source crawling

Persist source cursors/watermarks so runs focus on new or changed notices rather than repeatedly traversing identical history.

Suggested adapter state:

```text
source
query_family
last_cursor
last_page
last_publication_timestamp
last_success_at
known_notice_fingerprints
```

Historical backfills should be explicit modes, not accidental work repeated by every live run.

## 10. Source/query yield tracking

For every combination of:

```text
source × country × query_family × CPV/category
```

track:

```text
raw
new_unique
survived_hard_filters
small_llm_keep
GPT_keep
DCE_retrieved
GREEN
SUPER_GREEN
retrieval_failures
compute_seconds
```

The fleet controller should progressively allocate compute according to observed opportunity yield while reserving exploration capacity for new routes.

## 11. Bandit-style scheduler

Implement explore/exploit logic without requiring ML:

- favor source/query combinations producing genuine qualified opportunities;
- penalize high-duplicate / high-failure / zero-yield routes;
- reserve bounded exploration for new CPVs, geographies and sources;
- later incorporate actual bid/win/margin outcomes.

## 12. Long-lived workers and work stealing

Workers should amortize setup and browser/model initialization:

```text
start once
-> claim lease
-> process bounded batch
-> persist durable result
-> claim next available work
-> checkpoint/exit before platform runtime limit
```

Prefer queue-based work stealing over permanently assigning an oversized shard to one worker.

Maintain existing single-writer/lease/durable-upload guarantees.

## 13. Adaptive batching

Batch size should depend on work type:

- official API/page fetch: large;
- HTTP DCE downloads: medium/large;
- browser portal automation: small;
- local LLM triage: RAM/context constrained;
- deep DCE review: very small.

The controller should learn throughput and adjust batch targets from observed completion time.

## 14. Small local LLM layer

Follow `AGENTS.md` for the local-model cascade. Use small GGUF models for semantic triage/extraction, not final eligibility.

Rollout sequence:

```text
shadow scoring
-> benchmark against trusted GPT/human labels
-> inspect false negatives
-> set safe thresholds
-> automate obvious rejects/keeps only
-> continuously audit drift
```

## 15. Rejection reason ledger

Every rejected candidate should have a reason such as:

```text
duplicate
expired
wrong_category
wrong_geography
obvious_non_fit
budget_not_viable_when_verified
eligibility_blocker_verified
submission_constraint_blocker
DCE_unavailable
portal_barrier
insufficient_evidence
manual_review_needed
```

Do not convert UNKNOWN into a blocker.

## 16. Active learning from GPT Web

GPT Web should review the hard/high-value cases and leave behind structured labels that improve future deterministic/local-model triage.

```text
ambiguous candidate
-> GPT Web decision
-> structured label + rationale/evidence refs
-> benchmark corpus
-> threshold/rule/prompt refinement
```

The strategic goal is for expensive reasoning to create reusable intelligence rather than repeat the same judgment forever.

## 17. Business outcome feedback

When bids start being submitted, persist:

```text
bid_submitted
bid_abandoned + reason
eligibility_confirmed
clarification_required
shortlisted
won/lost
contract_value
expected_margin
realized_margin
```

Join outcomes back to source/query/CPV/features. Scheduler scoring should eventually optimize expected gross margin per compute hour, not volume.

## 18. Observability

Expose compact summaries readable by ChatGPT Web:

```text
raw/min
new unique/min
dedupe rate
hard-filter retention
small-LLM retention
GPT retention
DCE success rate
portal failure rate
GREEN / 1k raw
SUPER GREEN / 1k raw
compute seconds / GREEN
backlog by pipeline
oldest queue age
```

Large raw logs should remain available, but routine control should rely on concise state artifacts.

## 19. Cross-harvester core

Where practical, reuse infrastructure shared with GWS/hospitality:

```text
queue + leases
source adapters
normalization
dedupe
fetch cache
retry/backoff
worker telemetry
yield ledger
confidence routing
source provenance
feedback metrics
```

Do not unify business-specific scoring or evidence standards merely for code reuse.

## Implementation order

1. source/query/CPV yield ledger;
2. explicit rejection-reason schema;
3. incremental source cursors;
4. always-on speculative DCE queue;
5. three-pipeline decoupling (discovery / DCE / review);
6. shared fetch/content cache;
7. local small-LLM shadow classifier + benchmark;
8. embedding/positive-negative semantic prefilter;
9. work stealing + adaptive batch sizing;
10. closed-loop bid/win/margin feedback and adaptive scheduler.

## Non-negotiable principles

```text
GPT WEB IS THE HIGH-LEVEL ORCHESTRATOR, NOT AN API DEPENDENCY.
DETERMINISTIC FACTS FIRST.
SMALL LLM FOR SEMANTIC TRIAGE.
GPT WEB FOR HIGH-VALUE OR AMBIGUOUS REASONING.
DCE / AUTHORITATIVE EVIDENCE OWNS FINAL MANDATORY GATES.
DOWNLOAD PLAUSIBLE DCEs EARLY WHEN CHEAP.
PERSIST BEFORE WORKERS DIE.
MEASURE SOURCE YIELD.
OPTIMIZE EXPECTED OPPORTUNITY VALUE, NOT NOTICE COUNT.
UNKNOWN STAYS UNKNOWN.
```