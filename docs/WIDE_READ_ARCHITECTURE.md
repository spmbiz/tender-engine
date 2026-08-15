# GPT-first Live Tender Architecture

## Goal

GitHub is the acquisition and evidence transport layer. GPT is the semantic business-fit layer.

The system must not ask lexical heuristics to decide what is a Supergreen. The canonical flow is:

1. Harvest every currently discoverable tender from every enabled official lane.
2. Merge/dedupe into the canonical discovery corpus.
3. Build a fail-closed live snapshot of every row not proven expired by a parseable deadline.
4. Publish that snapshot both as durable GitHub Release assets and as a directly-readable `live-snapshot` branch that is force-replaced on every publication.
5. GPT reads the snapshot semantically and chooses candidate IDs for DCE retrieval.
6. GPT writes `control/gpt_dce_request.json` on `main`.
7. `GPT DCE Request Router` validates the request and explicitly dispatches `DCE Fanout V2` for only those IDs.
8. The DCE fleet downloads/extracts authoritative evidence and mandatory-gate snippets.
9. GPT deep-reads the substantive DCE output and only then may emit final bid/no-bid labels.

## Truth rules

- Missing evidence is `UNKNOWN`, never satisfied.
- A successful file/HTTP download is not proof that a substantive DCE was retrieved.
- Notice-only candidates cannot be `FINAL_SUPER_GREEN`.
- Pre-DCE score is capped at 89.
- For `SOLO_LEAN`, reject any opportunity requiring another entity's references/capacity, mandatory manufacturer/reseller status, regulated certification, forced consortium, licensed local trade, specialist onsite team, or another non-SPM execution dependency.
- Legacy keyword/heuristic prefilters may remain as optional background prefetch experiments, but they are not the source of truth for business-fit selection.

## Live snapshot products

After each successful `SuperGreen Discovery V2` run, `Live World Snapshot for GPT` publishes:

- immutable Release: `live-world-snapshot-<DISCOVERY_RUN>`
- stable Release: `live-world-snapshot-latest`
- direct-read branch: `live-snapshot`
- main pointer: `control/live_snapshot_latest.json`

The direct-read branch contains:

- `snapshot_manifest.json`
- `GPT_WIDE_READ_INSTRUCTIONS.md`
- `gpt-packets/packet-XXXX.jsonl`

The branch is force-replaced so hourly snapshots do not accumulate in repository history.

## GPT DCE request contract

```json
{
  "schema": "GPT_DCE_REQUEST_V1",
  "source_discovery_run": 123456789,
  "wide_read_run_id": 123456789,
  "default_preliminary_score": 84,
  "status": "DCE_PENDING",
  "mode": "SOLO_LEAN",
  "selection_reason": "GPT semantic wide-read of the complete live snapshot",
  "candidate_ids": ["SOURCE:ID", "SOURCE:ID2"]
}
```

Maximum request: 320 candidate IDs per wave.

## User interaction

When the user says **"analyse les sorties"**, the intended ChatGPT behavior is:

1. read `control/live_snapshot_latest.json`;
2. read `GPT_WIDE_READ_INSTRUCTIONS.md` and the packet files on ref `live-snapshot`;
3. perform semantic wide-read without trusting legacy keyword scores;
4. write a strict candidate selection to `control/gpt_dce_request.json`;
5. verify the router dispatched DCE retrieval;
6. when substantive DCE evidence is available, deep-read the 14 mandatory gates and report only evidence-backed final Supergreens.
