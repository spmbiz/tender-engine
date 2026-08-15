# SPM Exhaustive Every-Record Historical Read — FINAL MASTER

**STATUS: PASS**

- Structured procurement records individually materialized/scored: **18,271,075**
- Award rows scanned: **20,307,312**
- Award↔supplier links scanned: **19,958,186**

## Canonical grains

- Global Core v4 notice-first: **2,250,547**
- USAspending award-first: **15,842,317**
- AusTender award-first: **178,211**

## Integrity

### GLOBAL_CORE_V4
- PASS — ordinal 1..2,250,547; distinct IDs 2,250,547
- Known lane 70,246; open-world candidate 248,730; residual 1,931,571
- Procurement fingerprint `20756475576857774972166344`

### AUSTENDER_V1
- PASS — ordinal 1..178,211; distinct IDs 178,211
- Known lane 9,981; open-world candidate 43,194; residual 125,036
- Procurement fingerprint `1643141408666096695364443`

### USASPENDING_V1
- PASS — ordinal 1..15,842,317; distinct IDs 15,842,317
- Known lane 1,169,274; open-world candidate 1,430,750; residual 13,242,293
- Procurement fingerprint `146143675656265755023577377`

## Data-quality reconciliation

USAspending contains 15,842,317 procurement/award rows and 15,842,312 award↔supplier bridge rows in the canonical release. The five missing bridge links are retained as an observed source condition, not imputed.

## Boundary of the claim

This is an exhaustive read of the **canonical structured rows**, not a claim that millions of external DCE/PDF attachments were manually opened. Attachments are intentionally resolved selectively for live/final candidates because eligibility, references, turnover, insurance, language, onsite burden, pricing forms, and contractual obligations often exist only there.

Semantic lane labels are analytical classifications. They are not allowed to override source facts or convert UNKNOWN eligibility into PASS.
