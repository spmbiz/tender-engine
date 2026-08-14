# Super Green Tender Hunt — Agent Skill V2

## Purpose

Find **new, currently actionable public procurement opportunities** that a tiny AI-native digital operator can realistically bid and deliver. Preserve high recall: GPT should materially inspect the broad live opportunity pool before deterministic rules narrow it to DCE downloads.

This skill is the authoritative operating contract for GPT/Codex/agent-assisted tender hunting in this repository.

## Two non-negotiable truth rules

1. **GPT WIDE READ:** GPT must materially read every generated live-discovery packet before the DCE shortlist is finalized. Do not use keyword/CPV filters to hide unusual opportunities from GPT merely because their title does not resemble the known target categories.
2. **DCE GATE:** No opportunity may receive FINAL SUPER GREEN / score >= 90 until the DCE, RFQ, RFT, tender brief, or equivalent authoritative procurement pack has actually been retrieved and read for mandatory gates.

UNKNOWN stays UNKNOWN. Never invent throughput, eligibility, values, references, insurance requirements, or document content.

## Target operator

Optimize for a tiny Brussels-based AI-native operator that can directly deliver or coordinate:

- websites / CMS / lightweight software
- WebAR / interactive experiences when bounded
- graphic design / layout / publishing / illustration
- video / animation / editing / AI-assisted visual production
- OCR / digitization / document workflows
- translation / transcription / localization
- dashboards / automation / lightweight integrations
- commodity subcontracting or brokerage when eligibility and operational burden remain lean

Potentially attractive opportunities may have unexpected titles. Semantic reasoning beats a narrow keyword allowlist.

Hard warning signals include construction/heavy physical work, impossible turnover gates, mandatory reference history that cannot be evidenced, enterprise-scale SLA/support, mandatory local workforce, unattainable certifications, controlled documents, or disproportionate onsite burden.

## Freshness and canonical identity

Previously analyzed opportunities remain visible to the wide-read stage but must be marked `seen_before=true`. Do not present them as new unless explicitly rechecking a change/amendment.

Prefer canonical identifiers:

- TED publication number
- OCDS OCID / notice ID
- eTenders resourceId
- PCS notice reference
- PLACE consultation ID/reference
- portal-specific tender ID

Use `state/seen_candidates.jsonl` plus canonical dedupe. Mirrors/aggregators must not create duplicate opportunities.

# V2 operating pipeline

## Stage A — Parallel bulk discovery

Run public/official sources concurrently. Materialize identities, titles/descriptions, buyer, deadline, value when available, notice URL, portal, route identifiers, and source metadata.

Current V2 executors include:

- TED Search API: `pipeline/discover_ted.py`
- UK Contracts Finder OCDS: `pipeline/discover_contracts_finder.py`
- Ireland eTenders sharded browser enumerator: `pipeline/discover_etenders_ie.py`

Add more official source adapters over time rather than replacing high-recall discovery with generic web search.

Discovery output is raw material. Do **not** assign final eligibility here.

## Stage B — Canonical merge, dedupe, freshness annotation

Use:

`pipeline/merge_discovery.py`

Permitted deterministic operations before GPT wide-read:

- canonical dedupe
- normalization
- mark expired/current when reliable
- mark `seen_before`
- remove malformed rows with no material identity

Do not silently remove an unusual live opportunity solely because keywords/CPV/value heuristics think it is irrelevant.

## Stage C — GPT WIDE READ

Use:

`pipeline/wide_read_packets.py`

Default packet size: 250 materially enumerated opportunities.

GPT must read **every packet** generated for the live run. Parallelize packet reading across independent GPT agents/chats when useful, then merge decisions canonically.

For each opportunity, GPT may output:

- `QUEUE_DCE`
- `PASS_LOW_PRIORITY`
- `REJECT_OBVIOUS`
- `SEEN_NO_RECHECK`
- `UNCERTAIN_RESEARCH`

The purpose is semantic high-recall screening. GPT should actively look for non-obvious business models: subcontractable work, tiny lots inside large procedures, AI-fulfillable deliverables, brokerage, unusual digital/creative scopes, and small RFQs hidden behind generic titles.

Selected candidates must be emitted as JSONL following `queues/gpt_selections.example.jsonl`, for example:

```json
{"candidate_id":"IE:8670172","decision":"QUEUE_DCE","preliminary_score":88,"reason":"Bounded WebAR scope; verify DCE gates","packet":1}
```

Compile selections into the DCE queue with:

`pipeline/build_dce_queue_from_gpt.py`

## Stage D — Queue-driven DCE fan-out

Canonical queue:

`queues/dce_candidates.jsonl`

The queue must contain route data, not hardcoded Python `TARGETS=[...]` edits.

`.github/workflows/dce-fanout-v2.yml` compiles a dynamic GitHub Actions matrix with `pipeline/build_matrix.py` and fans independent candidates out concurrently.

`pipeline/dce_worker.py` selects the portal adapter from the candidate record.

Currently supported V2 adapters:

- Ireland eTenders
- France PLACE/Prado-style public DCE route
- Luxembourg PMP/Prado-style route
- Public Contracts Scotland public ZIP/postback route
- UNGM public document route
- direct HTTP / Contracts Finder attachments

Unsupported/auth/CAPTCHA routes must return explicit states rather than fabricate success.

## Stage E — Recursive document materialization

Every downloaded DCE is persisted with filename, byte size, SHA-256, source URL and retrieval status.

Use:

`pipeline/extract_corpus.py`

It recursively unpacks ZIP/7z/tar when possible and extracts text from PDF, DOCX, XLSX, PPTX and text-like files into:

- `candidate.json`
- `manifest.json`
- `document_index.json`
- `corpus.txt`

The full corpus remains available for GPT. Do not replace full reading with snippets alone.

## Stage F — Gate evidence extraction

Use:

`pipeline/extract_gates.py`

It extracts multilingual evidence windows for:

- turnover / financial capacity
- references / similar projects
- insurance
- tax clearance
- CVs / team
- languages
- certifications
- onsite/geographic burden
- subcontracting/consortium
- hosting/security/GDPR
- award criteria
- payment
- submission/deadline
- deliverables/scope

These snippets are retrieval aids, **not verdicts**.

## Stage G — GPT DEEP READ

`pipeline/aggregate_dce.py` produces `deep_review_queue.jsonl`.

For every successfully materialized candidate, GPT must read the relevant full `corpus.txt` and cross-check the gate snippets.

Resolve every material gate as one of:

- `PASS`
- `PASS_CONDITIONAL`
- `FAIL_HARD`
- `UNKNOWN`
- `NOT_APPLICABLE`

Explicitly inspect:

- turnover / accounts
- references and reference age/value/nature
- team/CVs
- insurance limits
- tax clearance timing
- certifications
- languages
- onsite/locality
- subcontracting / consortium / reliance
- IP/licensing
- hosting/security/GDPR
- SLA/support
- deliverables
- award criteria and minimum thresholds
- submission format
- deadline
- payment terms when specified

## Stage H — Targeted research only for unresolved facts

Web/research is a fallback cognition layer, not the primary bulk enumerator.

Use it for:

- unknown portal route discovery
- amendments/clarifications
- buyer mirrors
- legal/tax/insurance interpretation
- exact-reference public document mirrors
- questions left unresolved by authoritative tender documents

Once a portal route is solved and encoded in `portal_routes.py` / `DCE_ROUTE_MATRIX.md`, reuse the adapter instead of researching the same download path again.

## Stage I — Final classification

Separate **legal/selection eligibility** from **delivery difficulty**.

Recommended final classes:

- `SUPER_GREEN_VERIFIED` — >=90; DCE read; mandatory gates pass; delivery bounded
- `GREEN_VERIFIED` — 80–89; DCE read; viable with manageable caveats
- `CONDITIONAL` — materially attractive but unresolved gate(s)
- `REJECT_HARD` — explicit blocker or unacceptable burden
- `DCE_PENDING`
- `AUTH_REQUIRED`
- `INTEREST_RECORDING_REQUIRED`
- `CAPTCHA_REQUIRED`
- `ERROR_RETRYABLE`

Never force a positive quota.

# Parallelism contract

Parallelize independent work at all layers:

1. source discovery jobs
2. source page/shard enumeration
3. GPT wide-read packets
4. DCE candidates
5. extraction per candidate
6. GPT deep-review candidates
7. targeted research tasks

Do not serialize unrelated portals.

Keep bounded portal-level concurrency to avoid throttling. If GitHub hosted-runner startup dominates wall time, prefer fewer warm browser jobs with intra-job concurrency rather than hundreds of tiny browser jobs.

# Responsibility split

## GitHub / deterministic code

Own:

- bulk API/feed ingestion
- page enumeration
- normalization
- dedupe
- freshness annotation
- packet construction
- candidate queues
- portal routing
- DCE downloads
- archive extraction
- hashing/manifests
- text extraction
- evidence snippet extraction
- throughput telemetry

## GPT

Own:

- reading the broad opportunity pool, including unusual candidates
- semantic shortlist selection
- mandatory-clause interpretation
- cross-document reasoning
- delivery architecture
- subcontracting/brokerage insight
- risk assessment
- final scoring/classification
- bid strategy

GPT should not be used to click repetitive list pages or unzip files when scripts can do it, but it **should** be allowed to read thousands of normalized opportunities because semantic breadth can expose non-obvious gems.

# Run integrity / telemetry

Report exact counts and elapsed time:

- raw identities materialized per source
- canonical unique
- current/live unique
- wide-read packets and opportunities actually read
- GPT selections
- DCE queue count
- DCE successes / gated / errors
- files downloaded and bytes
- corpora extracted
- hard rejects after DCE
- conditional
- green
- Super Green
- stage and portal wall-clock times

Never claim a dataset headline count was processed unless the records were materially enumerated.

# Stop condition

A run may stop only when the requested workload is complete, sources are exhausted, or a legitimate terminal blocker is proven. Finding one attractive candidate is not a stop condition.
