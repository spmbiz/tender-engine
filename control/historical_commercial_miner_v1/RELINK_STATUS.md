# Historical Commercial Miner v1 — canonical relink status

**COMPUTE STATUS: PASS**

Canonical rerun: `31910254263`.

The rerun recomputed all three historical warehouses after the cross-grain identity resolver was corrected to prefer `Historical_Tender_ID` over native/source `Tender_ID` where both exist.

All source compute/publish jobs passed:

- Global Core v4 notice-first: **2,250,547** procurement records — PASS.
- AusTender award-first: **178,211** procurement records — PASS.
- USAspending award-first: **15,842,317** procurement records — PASS.

Reconciled corpus totals remain:

- **18,271,075** procurement records;
- **20,307,312** award rows;
- **19,958,186** award↔supplier links.

The `consolidate` job's final Git persistence step failed only because concurrent historical-analysis workflows modified `control/historical_commercial_miner_v1/MASTER_SUMMARY.json` while the job was rebasing. The master file on `main` already contains the corrected relinked source summaries and PASS totals, and the derived source assets were published before that Git race.

This is therefore **not a computation/data failure**. Future historical interpretation should use the current relinked outputs and should not use pre-relink supplier-concentration outputs as authority.
