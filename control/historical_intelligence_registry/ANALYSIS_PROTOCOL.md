# Historical Intelligence Analysis Protocol

This file defines the persistence behavior for every future historical-analysis pass.

## Mandatory outputs per pass

Every materially new analysis should leave four durable traces:

1. **Evidence output** under `control/historical_*` and/or a durable GitHub Release.
2. **Classification decision** in `CLASSIFICATION_DECISIONS.jsonl` when a named family is promoted, held, rejected, corrected or superseded.
3. **Model hypothesis update** in `MODEL_HYPOTHESES.md` when GPT's strategic interpretation changes materially.
4. **Current-state pointer** in `CURRENT_STATE.md` summarizing what is authoritative and what remains open.

## No-loss semantics

Allowed record dispositions:

- `PRESERVE`
- `PRESERVE_AND_RECLASSIFY`
- `PRESERVE_AND_HOLD`

There is intentionally **no `DELETE` disposition** in the historical intelligence layer.

A false classifier result means the mapping was wrong, not that the procurement ceased to exist or became commercially irrelevant.

## Decision vocabulary

- `PROMOTED_CLASSIFICATION` — representative evidence supports the semantic family.
- `HOLD_CLASSIFICATION` — plausible but not yet adequately supported.
- `REJECTED_CLASSIFICATION` — semantic interpretation disproven; underlying records remain.
- `SUPERSEDED_CLASSIFICATION` — an older classifier/version has been replaced by a better one.
- `PROMOTED_HYPOTHESIS` — strategic thesis deserves deeper economic analysis.
- `WEAKENED_HYPOTHESIS` — thesis remains possible but evidence is less supportive.
- `REJECTED_HYPOTHESIS` — business thesis not supported; records still remain available for other theses.

## Asymmetry discipline

Do not rank purely by contract value or historical score. For SPM-specific opportunity analysis, separately assess:

- AI/labor compression;
- supplier/talent sourcing arbitrage;
- remote-delivery potential;
- repeatability/standardization;
- buyer breadth;
- supplier concentration;
- incumbent/channel barriers;
- licenses/certifications/clearance;
- physical logistics/onsite burden;
- working-capital/pre-financing burden;
- ability to subcontract or aggregate specialists;
- likely gross-margin structure.

## Open-world reservation

At least one discovery pass must always remain ontology-independent. Known lanes may be used to *exclude from a review queue* for diversity, but never to suppress or delete underlying records.

## Historical-vs-live firewall

Historical analysis can establish market structure, prior buyer behavior, supplier fragmentation, price bands, recurrence and business hypotheses. It cannot establish current tender eligibility, current deadline, current DCE gates or final bid/no-bid.
