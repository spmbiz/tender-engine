# Historical Intelligence Registry

Purpose: durable, append-oriented memory for the historical tender intelligence program.

## Non-loss rule

A record is never deleted or discarded because a classifier, ontology, GPT review, regex, or hypothesis is rejected.

`REJECTED_CLASSIFICATION` means only: **the proposed interpretation was false or unsupported**. The underlying procurement record remains in the canonical archive and is eligible for reclassification, open-world discovery, and later review.

Examples:
- `ICT_HARDWARE_VAR — France` was a bad label because `Var` was usually the French department, not `Value Added Reseller`. The 610 matched records remain valid historical procurements and must remain discoverable in their true categories.
- `PROCUREMENT_AGENT — France` was a bad business-family interpretation because many titles described purchases made *for/by a centrale d'achat*, not a supplier being hired as a procurement agent. Those records remain valid and must be routed back to their actual goods/services families.

## Evidence layers

1. `FACT` — directly measured from canonical historical records / award / supplier grains.
2. `CLASSIFICATION` — semantic family assignment supported by representative titles.
3. `MODEL_HYPOTHESIS` — GPT interpretation about business attractiveness, fulfillment model, asymmetry, likely barriers or strategic fit. Never treated as source fact.
4. `VERDICT` — promote / hold / reject-classification / superseded, with reason and evidence pointer.
5. `FOLLOWUP` — next analysis required.

## Persistence contract

- Canonical raw archives and release assets remain immutable authority.
- Derived files under `control/historical_*` are reproducible analysis outputs.
- This registry records what was believed, why, when, and what superseded it.
- Never overwrite history silently. A changed view gets a new ledger entry pointing to the superseded one.
- Unknown remains UNKNOWN.
- Historical attractiveness never proves current eligibility or live bidability.

## Current program goal

Map the entire historical procurement archive into commercially meaningful markets, with special emphasis on:

- overlooked / previously unnamed markets;
- lean remote-delivery opportunities;
- AI-compressible labor;
- cross-border supplier and freelancer arbitrage;
- broker / reseller / aggregator models;
- standardized-goods sourcing;
- document / content / data operations;
- markets where SPM's automation, sourcing and research stack can create asymmetric cost or speed advantages.

This registry is historical-only. Live discovery and DCE adjudication are separate systems.
