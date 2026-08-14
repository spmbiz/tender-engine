# Tender Hunt Parallelization & Performance Audit

## Executive diagnosis

The current repository proves that many portal routes work end-to-end, but the operating model is still **probe-driven rather than pipeline-driven**.

The biggest performance issue is not raw HTTP speed. It is orchestration overhead:

- target IDs are often hardcoded into one-off scripts
- changing candidates frequently requires a commit
- browser dependencies are reinstalled across many independent workflows
- several independent portal probes execute serially inside a single job
- discovery, DCE retrieval, extraction, and GPT reasoning are loosely coupled by human/GPT intervention
- artifacts expire after a few days and are not yet treated as a durable evidence store
- candidate dedupe/freshness is not enforced centrally before expensive retrieval
- downloaded DCEs are not consistently converted into a normalized machine-readable gate record before GPT sees them

The result: the system can discover Barnagh, but it cannot yet do Barnagh-style verification for dozens of candidates per pass with low latency.

## Current bottlenecks

### 1. Hardcoded candidate probes

Example: `fresh_ireland_probe.py` contains a literal `TARGETS=[...]` array.

Impact:

- a new candidate requires editing code
- each edit triggers a new workflow setup
- candidate selection and adapter logic are mixed together
- no generic queue/fan-out exists

Fix:

- adapters must accept candidate metadata through CLI/JSON/stdin
- candidate IDs belong in a queue artifact/database, not source code

### 2. Serial browser adapters

`dce-resolver.yml` runs UNGM, Ireland, PCS, e-Vergabe, and ProContract one after another in the same browser job.

Impact:

- a slow portal delays all later portals
- one timeout can consume a large share of the 30-minute job
- independent routes cannot use GitHub runner parallelism

Fix:

- GitHub Actions matrix by portal/shard
- one adapter invocation per matrix unit or bounded batch
- `fail-fast: false`

### 3. Repeated environment setup

Multiple workflows repeatedly:

- checkout
- setup Python
- pip install Playwright
- install Chromium + OS deps

Impact:

- large fixed overhead relative to 20–60 second retrieval tasks
- many small hunts spend more time preparing runners than harvesting

Fix options:

1. consolidate compatible browser work into a reusable container image with Playwright preinstalled
2. use `mcr.microsoft.com/playwright/python` or equivalent pinned image where compatible
3. cache Python packages/browser assets when runner behavior permits
4. keep a self-hosted runner/VPS for high-frequency browser retrieval

Best long-term answer: a small always-on worker/VPS or container service; keep GitHub Actions for orchestration/fallback.

### 4. Sequential page enumeration

`etenders_deep_scan.py` loops pages 1..20 sequentially with one browser page.

Impact:

- latency grows linearly with depth
- one page timeout can stall the scan
- no sharding

Fix:

- shard page ranges: 1–5, 6–10, 11–15, 16–20 in parallel
- preferably identify underlying HTTP/XHR endpoints and remove Playwright from discovery entirely
- discovery should be HTTP/API-first, browser-last

### 5. Static clock/date logic

Several scripts contain literal timestamps/dates such as 2026-08-14.

Impact:

- future runs silently misclassify deadlines
- code must be edited to remain current

Fix:

- always use current UTC time dynamically
- normalize source timezone explicitly

### 6. Regex-only discovery ranking

Current ranking is primarily keyword regex + value.

Impact:

- false negatives for unusual wording
- false positives for irrelevant services using generic words such as "design" or "media"
- no learned pattern from previous hard rejects

Fix:

Use a two-stage ranker:

1. deterministic cheap score from structured fields
2. batched LLM semantic prescreen on only the top few hundred records

The LLM prescreen must never replace DCE verification.

### 7. No central seen/rejected index before expensive work

Freshness exclusions currently depend too much on conversation memory/manual knowledge.

Fix:

Maintain a durable canonical index with states such as:

- SEEN
- PRESCREEN_REJECT
- DCE_PENDING
- DCE_RETRIEVED
- REJECT_HARD
- CONDITIONAL
- GREEN_VERIFIED
- SUPER_GREEN_VERIFIED
- EXPIRED

Key by canonical opportunity ID plus lot where applicable.

Check this index before browser retrieval.

### 8. DCE retrieval and DCE understanding are separated by a human loop

Current pattern:

`GitHub downloads artifact -> GPT fetches/downloads artifact -> manually inspects/extracts -> reasons`

Impact:

- high agent/tool latency
- repeated zip inspection
- poor batchability

Fix:

Automate deterministic extraction immediately after retrieval:

- recursive archives
- PDF text
- DOCX text/tables
- XLSX sheets/values
- HTML/text
- file inventory

Produce one normalized `evidence.json` plus `corpus.txt` per candidate.

GPT should receive those outputs directly, not raw archives unless needed.

### 9. No automatic gate extractor

The most valuable part of DCE reading is repetitive: turnover, references, insurance, languages, team, certifications, onsite, etc.

Fix:

Before full GPT reasoning, run deterministic lexical extraction around high-value terms and store snippets with provenance.

Example output:

```json
{
  "turnover_mentions": [{"file":"RFT.docx","text":"minimum turnover..."}],
  "insurance_mentions": [...],
  "reference_mentions": [...]
}
```

This makes GPT qualification faster and easier to audit.

### 10. Ephemeral artifacts

Many Actions artifacts have 7-day retention.

Impact:

- evidence disappears
- re-analysis requires re-downloading portals
- amendments/change detection become harder

Fix:

Persist final manifests/extracted corpora/hashes to durable storage:

- Google Drive private folder, or
- object storage such as R2/S3, or
- private repo/releases for non-sensitive small text metadata

Never commit supplier credentials/session states to the public repo.

## Recommended v2 topology

```text
                         +------------------+
                         | Freshness / Seen |
                         | canonical index  |
                         +---------+--------+
                                   |
          +------------------------+------------------------+
          |                        |                        |
   DISCOVER TED             DISCOVER UK              DISCOVER IE ...
   API worker               OCDS worker               source worker
          |                        |                        |
          +------------------------+------------------------+
                                   |
                            NORMALIZE + DEDUPE
                                   |
                            CHEAP STRUCTURED SCORE
                                   |
                         BATCH GPT PRE-SCREEN
                                   |
                         candidate queue top N
                                   |
           +-----------------------+-----------------------+
           |                       |                       |
      DCE worker IE           DCE worker PLACE       DCE worker UNGM ...
      matrix shard            matrix shard            matrix shard
           |                       |                       |
           +-----------------------+-----------------------+
                                   |
                       recursive unpack + extraction
                                   |
                           evidence/gate snippets
                                   |
                     PARALLEL GPT DCE QUALIFICATION
                                   |
                              FINAL MERGE
                                   |
                   MASTER + durable evidence + alerts
```

## Unit of parallelism

The correct unit changes by stage.

### Discovery

Parallelize by source and pagination shard.

Example:

- Contracts Finder pages/cursors: HTTP concurrency
- eTenders pages: 4 shards
- TED query partitions: date/CPV/value shards
- UNGM pages: source shards

### DCE retrieval

Parallelize first by portal, then by candidate with bounded concurrency.

Do **not** open 50 concurrent browser contexts against the same procurement portal.

Recommended initial caps:

- direct HTTP docs: 8 concurrent
- same portal browser work: 2–3 concurrent
- cross-portal browser jobs: 6–10 in parallel

### Document extraction

Parallelize by candidate/file using CPU workers.

### GPT reasoning

Batch preliminary semantic screens. For deep DCE qualification, parallelize candidates because their evidence is independent.

## GitHub Actions design

### Bad current pattern

```yaml
- run: python ungm_probe.py
- run: python ireland_probe.py
- run: python pcs_probe.py
- run: python evergabe_probe.py
- run: python procontract_probe.py
```

### Better pattern

```yaml
strategy:
  fail-fast: false
  matrix:
    portal: [UNGM, IRELAND_ETENDERS, SCOTLAND_PCS, EVERGABE, PROCONTRACT]
steps:
  - run: python dce_worker.py --portal "${{ matrix.portal }}" --queue queue.jsonl
```

Then shard large per-portal queues:

```yaml
matrix:
  shard: [0,1,2,3]
```

Each worker takes `hash(candidate_id) % shard_count == shard`.

## Target performance envelope

A realistic v2 target for one hunt pass:

- 5,000–25,000 raw records enumerated across bulk APIs: minutes, not hours
- 500–2,000 deterministic candidate matches
- 100–300 semantic prescreens
- 20–50 DCE retrieval attempts
- 10–30 successfully extracted DCE packs
- 10–30 deep qualifications in parallel
- end-to-end shortlist latency: target 10–25 minutes once routes are warm

The final number of Super Greens remains unconstrained; zero is valid.

## GPT efficiency changes

### Current

GPT spends time:

- finding portal mechanics
- modifying scripts per candidate
- polling workflow runs
- downloading archives
- manually finding relevant files
- manually searching for eligibility language

### v2

GPT should spend time only on:

1. semantic prescreen of normalized candidates
2. interpretation of extracted evidence
3. delivery feasibility
4. final prioritization and bid strategy

Everything else should be deterministic code.

## Research efficiency changes

Use web research for route discovery once, then encode the result in the adapter registry.

A successful route should graduate through states:

`RESEARCHED -> ROUTE_IDENTIFIED -> DOWNLOAD_VALIDATED -> PRODUCTION_ADAPTER`

Once in `PRODUCTION_ADAPTER`, GPT should not rediscover how that portal works on every run.

## Recommended implementation order

### P0 — highest ROI

1. Replace hardcoded target arrays with `queue.jsonl` input.
2. Create generic adapter interface / `dce_worker.py`.
3. Matrix-parallelize portal workers.
4. Dynamic time/deadline handling everywhere.
5. Central durable seen/dedupe index.
6. Automatic recursive extraction + normalized text corpus.

### P1

7. Gate-snippet extractor.
8. Batch LLM prescreen and deep qualification schemas.
9. Durable evidence storage and change detection.
10. Automatic MASTER persistence/readback.

### P2

11. Self-hosted warm Playwright worker to eliminate setup overhead.
12. Authenticated portal states through encrypted secrets/private storage.
13. Amendment watcher and automatic DCE re-analysis when hashes change.

## Core metric

Optimize for:

**verified viable opportunities per minute of expensive browser + GPT time**

—not raw notices scraped, not preliminary green scores, and not number of workflow runs.
