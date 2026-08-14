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
Persist in a private canonical blob store such as Google Drive or S3-compatible object storage:

- original downloaded DCE / procurement source files
- original downloaded ZIP / 7z / PDF / DOC / DOCX / XLSX / PPTX payloads
- extracted canonical `corpus.txt`
- `document_index.json`
- `gate_snippets.json`
- `candidate.json`, `manifest.json`, portal/TED resolution records
- useful portal-page evidence when no document payload was obtainable

Recursive unpacked copies do **not** need separate durable storage when they are deterministically reproducible from the preserved source archive and their extracted text/index are preserved.

### C. Temporary transport/debug data
GitHub Actions artifacts may hold:

- shard handoff data
- canonical-staging bundles awaiting external persistence
- deep-review queues
- short-lived debugging output

They must have short retention **only when a durable canonical copy exists or there is enough retention buffer to complete canonicalization safely**.

## Canonicalization gate

No cleanup of a raw/staging artifact is permitted unless all of the following are true:

1. A canonical manifest exists.
2. Every expected candidate/source group is covered exactly once.
3. Every persisted file has a byte size and SHA-256 hash.
4. The external canonical store reports successful writes.
5. The canonical object IDs / locations are recorded durably.
6. The durable copy has been read back or metadata-verified.
7. The run is marked `CANONICAL_VERIFIED`.

If any step fails, status is `CANONICAL_BLOCKED` and the temporary artifact must remain available long enough to retry. Never convert a persistence failure into data deletion.

## Storage minimization rules

Storage is minimized by eliminating duplication, not by discarding unique data:

- preserve each original source blob once, content-addressed by SHA-256 where possible;
- deduplicate identical source files across candidates/runs by hash;
- do not persist recursively unpacked binary duplicates when original archives are preserved;
- keep one canonical extracted corpus and one evidence/index set per candidate/version;
- aggregate artifacts must not re-embed all shard blobs merely for convenience;
- slim GPT handoffs should contain text/evidence, not source binaries;
- use short-lived transport artifacts after canonical persistence is verified;
- retain source URL + retrieval time + hash even when a source is later re-fetched.

## Current canonical store

A private Google Drive folder is currently used as an available durable store for harvested run bundles:

`Public Tender Intelligence — Canonical Harvests`

Folder ID: `1qCWoo7msDwa20tuBTInoxmYOBC_r9Rjo`

The repository remains the durable structured-state/index layer; Drive is the current blob/archive layer. A future S3/R2 backend may replace or mirror Drive without changing the invariant above.

## Cleanup semantics

`CONSOLIDATED`, `AGGREGATED`, `ANALYZED`, or `UPLOADED_AS_ANOTHER_ARTIFACT` do **not** mean canonicalized.

Only `CANONICAL_VERIFIED` authorizes deletion of temporary artifacts.
