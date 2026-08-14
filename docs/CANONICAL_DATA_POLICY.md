# Canonical Data Policy

## Non-negotiable invariant

GitHub Actions artifacts are a temporary transport/debug layer. They are never the canonical data store.

**Never delete or allow unique harvested data to expire merely to save Actions artifact storage.**

A run is safe to clean only after all valuable unique data is durably persisted and the persistence receipt has been verified.

## Data classes

### A. Durable structured state
Persist indefinitely in the repository / MASTER where appropriate:

- candidate IDs and source IDs
- source URLs and portal routes
- discovery timestamps and deadlines
- canonical dedupe / seen state
- qualification verdicts and scores
- mandatory-gate evidence summaries
- run throughput / yield metrics
- document manifests, byte sizes and SHA-256 hashes
- canonical-store receipts / object IDs

### B. Durable source and analysis payloads
Persist outside GitHub Actions artifact storage:

- original downloaded DCE / procurement source files
- original downloaded ZIP / 7z / PDF / DOC / DOCX / XLSX / PPTX payloads
- extracted canonical `corpus.txt`
- `document_index.json`
- `gate_snippets.json`
- `candidate.json`, `manifest.json`, portal/TED resolution records
- useful portal-page evidence when no document payload was obtainable

Recursive unpacked copies do **not** need separate durable storage when they are deterministically reproducible from the preserved source archive and their extracted text/index are preserved.

### C. Temporary transport/debug data
GitHub Actions artifacts may hold only short-lived handoff/debug payloads when necessary. They are not evidence of persistence.

## Canonical stores

### Automated public-data canonical store: GitHub Releases

For publicly downloadable procurement data, each DCE run creates a durable GitHub Release named `dce-harvest-<run_id>`.

Each candidate is persisted as a separate canonical pack containing:

- the exact original downloaded source files;
- candidate + manifest metadata;
- route/TED resolution data where available;
- extracted corpus;
- document index;
- mandatory-gate snippets;
- an internal inventory with size + SHA-256 for every preserved file.

The Release also receives the canonical shard index and consolidated deep-review pack. GitHub Actions artifacts are therefore unnecessary for normal public-DCE persistence.

### Private / mirror canonical store: Google Drive

Critical runs may additionally be mirrored to the private Drive folder:

`Public Tender Intelligence — Canonical Harvests`

Folder ID: `1qCWoo7msDwa20tuBTInoxmYOBC_r9Rjo`

Drive is also the preferred fallback for data that should not be exposed in a public GitHub Release. Authenticated, restricted, confidential, or non-public portal material must not be published to a public Release merely for convenience.

A future S3/R2 backend may replace or mirror Drive without changing the invariant.

## Canonicalization gate

No cleanup of a raw/staging artifact is permitted unless all of the following are true:

1. A canonical manifest exists.
2. Every expected candidate/source group is covered exactly once.
3. Every persisted file has a byte size and SHA-256 hash.
4. The canonical store reports successful writes.
5. The canonical object IDs / release assets / Drive file IDs are recorded durably.
6. The durable copy has been read back or metadata-verified.
7. The run is marked `CANONICAL_VERIFIED`.

If any step fails, status is `CANONICAL_BLOCKED` and temporary data must remain available long enough to retry. Never convert a persistence failure into data deletion.

## Storage minimization rules

Storage is minimized by eliminating duplication, not by discarding unique data:

- preserve each original source blob once, content-addressed by SHA-256 where possible;
- deduplicate identical source files across candidates/runs by hash;
- do not persist recursively unpacked binary duplicates when original archives are preserved;
- keep one canonical extracted corpus and one evidence/index set per candidate/version;
- do not create an aggregate copy that re-embeds every source blob merely for convenience;
- slim GPT handoffs contain text/evidence, not source binaries;
- use Release assets / Drive as canonical storage and avoid Actions artifacts for durable payloads;
- retain source URL + retrieval time + hash even when a source is later re-fetched.

## Current verified mirror receipts

Durable Drive receipts are recorded in `state/canonical_receipts.jsonl`.

The 2026-08-14 wide-read run `31836655668` and DCE mega-run `31838467001` have verified Drive copies. The DCE run was re-packed into five complete chunks plus a canonical manifest so every transfer remained below the Drive connector's 100 MB transfer limit.

## Cleanup semantics

`CONSOLIDATED`, `AGGREGATED`, `ANALYZED`, `UPLOADED_AS_ANOTHER_ARTIFACT`, or `REPACKED` do **not** mean canonicalized.

Only `CANONICAL_VERIFIED` authorizes deletion of temporary transport data.
