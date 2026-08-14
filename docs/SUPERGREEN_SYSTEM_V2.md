# SuperGreen System V2 — Implemented Architecture

This document describes the implemented GPT × GitHub × procurement-document workflow used to turn broad public-tender discovery into DCE-verified opportunities.

Authoritative agent behavior is in `skills/supergreen-hunt/SKILL.md`.

## Design decision: GPT wide-read stays broad

The system intentionally does **not** keyword-filter the live pool before GPT sees it.

Why: non-obvious opportunities can be hidden behind generic titles, unusual CPVs, lots, subcontractable scopes, or descriptions that only become interesting under semantic reasoning.

Deterministic code may normalize, dedupe, identify expiry, and mark already-seen opportunities. It should not silently remove a materially enumerated live opportunity merely because it does not resemble a known target keyword.

## Pipeline

```text
OFFICIAL/PUBLIC DISCOVERY
  TED Search API ─────────────┐
  Contracts Finder OCDS ─────┼── parallel
  eTenders Ireland ──────────┘
              │
              ▼
CANONICAL MERGE + DEDUPE + seen_before
              │
              ▼
GPT WIDE-READ PACKETS (default 250 records)
  GPT reads every packet; packets may be assigned to independent agents in parallel
              │
              ▼
gpt_selections.jsonl
              │
              ▼
DCE QUEUE
              │
              ▼
2 GitHub shards × bounded local concurrency
              │
              ▼
TED BT-15 / portal adapter / public docs
              │
              ▼
DCE FILES + SHA256
              │
              ▼
recursive ZIP/7z unpack + PDF/DOCX/XLSX/PPTX extraction
              │
              ▼
corpus.txt + document_index.json + gate_snippets.json
              │
              ▼
GPT DEEP READ OF FULL DCE
              │
              ▼
PASS / PASS_CONDITIONAL / FAIL_HARD / UNKNOWN
              │
              ▼
FINAL CLASSIFICATION
```

## Discovery executors

### TED

`pipeline/discover_ted.py`

Uses the official TED v3 Search API and iteration pagination. Target is broad ACTIVE-scope enumeration with no semantic keyword prefilter. The Search API can return up to 250 notices per iteration page.

### UK Contracts Finder

`pipeline/discover_contracts_finder.py`

Uses the official OCDS endpoint. No keyword prefilter. Materializes notice identity, title, description, deadline, value, buyer, documents and suitability metadata when present.

### Ireland eTenders

`pipeline/discover_etenders_ie_async.py`

Uses one warm Playwright browser and concurrent page fetches. HTML is parsed with BeautifulSoup rather than expensive row-by-row browser locator calls.

The runner reuses preinstalled Chrome when available; Playwright Chromium installation is only a fallback.

## Discovery orchestration

`.github/workflows/supergreen-discovery-v2.yml`

Optimized for the observed GitHub concurrency constraint:

- Worker A: TED + Contracts Finder API scripts concurrently inside one runner.
- Worker B: one warm Chromium for Ireland, multiple pages concurrently.
- Merge/packet job runs after discovery.

Workflow concurrency cancels stale development/discovery runs instead of allowing a backlog of obsolete runs.

## Canonical merge / seen index

`pipeline/merge_discovery.py`

Produces:

- `merged/candidates.jsonl`
- `merged/current_candidates.jsonl`
- `merged/stats.json`

`state/seen_candidates.jsonl` marks opportunities already analyzed. They remain visible to GPT but must not be presented as fresh unless changed/rechecked.

## GPT wide-read

`pipeline/wide_read_packets.py`

Produces numbered `.md` and `.jsonl` packets plus a manifest.

GPT's selection schema is shown in:

`queues/gpt_selections.example.jsonl`

Example:

```json
{"candidate_id":"IE:8670172","decision":"QUEUE_DCE","preliminary_score":88,"reason":"Bounded WebAR/animation scope; verify DCE gates","packet":1}
```

Compile GPT selections with:

```bash
python pipeline/build_dce_queue_from_gpt.py \
  --candidates merged/current_candidates.jsonl \
  --selections gpt_selections.jsonl \
  --out queues/dce_candidates.jsonl
```

## DCE retrieval V2

`.github/workflows/dce-fanout-v2.yml`

The workflow no longer creates one cold GitHub runner per tender. It compiles at most two runner shards using:

`pipeline/build_dce_shards.py`

Each shard installs browser/runtime dependencies once, then processes candidate lines with bounded in-runner concurrency using:

`pipeline/dce_batch_worker.py`

Per-candidate work is handled by:

`pipeline/dce_worker_v2.py`

Supported V2 routes currently include:

- TED -> BT-15 -> supported downstream adapter
- Ireland eTenders
- France PLACE / Prado-style flow
- Luxembourg PMP / Prado-style flow
- Public Contracts Scotland public ZIP/postback route
- UNGM public documents
- direct HTTP documents / Contracts Finder attachment URLs

Unsolved routes return explicit states such as `AUTH_REQUIRED`, `CAPTCHA_REQUIRED`, `INTEREST_RECORDING_REQUIRED`, `TED_DOWNSTREAM_ADAPTER_PENDING`, or `ERROR_RETRYABLE`.

## TED bridge

`pipeline/ted_resolver.py`

For a selected TED notice:

1. resolve publication number;
2. query Search API for canonical notice-format URLs;
3. retrieve parseable eForms/XML;
4. extract `CallForTendersDocumentReference` / BT-15 URI values;
5. classify the downstream portal;
6. reuse the relevant DCE adapter.

This prevents GPT-selected TED opportunities from becoming dead ends between discovery and document analysis.

## DCE materialization

`pipeline/extract_corpus.py`

Recursively expands archives and creates:

- `candidate.json`
- `manifest.json`
- `document_index.json`
- `corpus.txt`

Every persisted file has size and SHA-256.

`pipeline/extract_gates.py` creates retrieval windows for turnover, references, insurance, tax clearance, team/CVs, language, certifications, onsite burden, subcontracting/consortium, security/GDPR, award criteria, payment, deadlines and deliverables.

Gate snippets do **not** replace full DCE reading.

`pipeline/aggregate_dce.py` builds the GPT deep-review queue.

## Mandatory final gate

No score >= 90 / `SUPER_GREEN_VERIFIED` unless GPT has read the authoritative DCE/equivalent and resolved all material mandatory gates.

A tender that looks excellent from the notice but whose DCE is not read remains `DCE_PENDING` / `CONDITIONAL`.

## Measured benchmark — first V2 discovery run

Before TED was added and before warm-browser optimization:

- 7,862 canonical unique records materialized across UK + Ireland history slices.
- 845 current/live unique records remained.
- Contracts Finder: 3,488 records materially enumerated over 35 pages in roughly 31 seconds of actual enumeration.
- Ireland: a 1,000-record / 10-page shard took roughly 24 seconds of actual scanning, but browser install/startup added around 30 seconds of dead time.
- Wide-read output: 4 packets for the 845 live records.

This benchmark directly motivated the warm-browser and two-runner redesign.

## Measured DCE smoke test

Barnagh Greenway Hub (`IE:8670172`) passed the queue-driven V2 end to end:

- queue record -> generic Ireland adapter
- real DCE ZIP downloaded
- ZIP size: 2,156,040 bytes
- SHA-256: `780d91c4347721ea6f91e298296c7cabb6601d2041721606ce8634d340349182`
- files unpacked
- PDF text extracted
- `corpus.txt` built
- gate snippets generated
- deep-review artifact generated

The important result is architectural: Barnagh no longer required editing a Python `TARGETS=[...]` list.

## Main remaining expansion work

The core V2 is operational, but route coverage can still improve. Priority adapters:

- Belgian e-Procurement
- EU Funding & Tenders
- TenderNed
- German e-Vergabe download finalization
- authenticated Mercell/ProContract using encrypted browser state
- France AWS/Achatpublic where CAPTCHA/auth rules permit
- Quebec/Canada/Australia document routes

These are adapter expansion tasks, not redesigns of the core pipeline.

## Optimization principle

Optimize for:

`authoritatively DCE-verified viable opportunities / minute`

—not raw notice count alone.

But preserve broad GPT visibility upstream: volume and semantic breadth are deliberate parts of the strategy.
