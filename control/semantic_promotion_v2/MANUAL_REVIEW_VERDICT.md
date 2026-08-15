# Semantic Promotion v2.1 — Manual Review Verdict

This is the human semantic gate downstream of `SPM_SEMANTIC_PROMOTION_V2_1_MANUAL_QA`. Automatic counts are not enough for promotion.

## PROMOTE_BROKER — Software licences / SaaS resale

- Strict historical hits: **438**
- OPEN_PUBLIC hits: **92**
- Manual review: **PASS** on the persisted 40-row cross-source sample after title-level software-licensing hardening.
- Observed sample semantics are actual software licences, subscriptions, renewals, maintenance/support bundles, or software licensing frameworks across Belgium, Canada, France, Germany and Ireland.
- The earlier false-positive class caused by generic professional `licence renewal` language was removed before this verdict.
- Live use: **small broker/resell discovery prior only**. DCE must still verify reseller/partner authorization, manufacturer channel restrictions, implementation/support scope, payment terms, working capital, warranty/liability and any framework admission restrictions.
- It is **not** AI-native fulfilment and must not inherit CORE_DIGITAL economics.

## PROMOTE_BROKER — Promotional merchandise

- Strict historical hits: **142**
- OPEN_PUBLIC hits: **97**
- Manual review: **PASS** on the persisted 40-row cross-source sample.
- Sample is overwhelmingly genuine branded/promotional merchandise, apparel, gifts, personalized objects, fulfilment and related supply frameworks across Belgium, Canada, France, Ireland, Quebec and TED countries.
- Live use: **small broker/resell discovery prior only**. DCE must verify samples, sustainable/material specifications, personalization, minimum quantities, storage/fulfilment, delivery geography, framework burden and subcontracting.

## HOLD_MANUAL_QA — Training / e-learning

- Automatic strict hits: **1,544**; OPEN_PUBLIC: **680**.
- Manual review: **FAIL for broad promotion** despite the large count.
- Persisted accepted sample still contains semantic collisions such as asbestos works for a `Learning Center`, physical engineering training systems, unrelated training/professional-service scopes, fire-service appliances and furniture where learning terminology appears incidentally.
- Genuine sub-lanes clearly exist (LMS/SaaS, e-learning module production, Moodle, digital authoring), but the current broad cohort is not clean enough to alter live ranking.
- Live use: **no expansion bonus** until a narrower title/scope classifier is separately QA-reviewed.

## HOLD / REJECT decisions preserved

- Hardware / AV resale: `HOLD_BROKER` — installation, warranty, working-capital and physical-delivery burden dominate too often.
- Office supplies / consumables resale: `HOLD_BROKER` — high commodity volume is not evidence of useful margin.
- Uniforms / PPE resale: `HOLD_BROKER` — standards, sizing, samples and inventory risk.
- Signage / display production: `HOLD_BROKER` — installation/site burden is frequent.
- Event support / production: `HOLD` — onsite/cadence burden remains common.
- Courier / mail fulfilment: `REJECT_CORE` — physical network operation.
- Recruitment / temporary staffing: `REJECT_CORE` — employer/labour/compliance operating model.

## Safety boundary

Promotion means **historical discovery prior only**. It cannot satisfy live eligibility, references, turnover, insurance, certifications, language, onsite, subcontracting, pricing or contractual gates. Those remain DCE-controlled.
