# Historical Intelligence Lab

This namespace is deliberately **historical-only**.

Mission: mine the canonical structured procurement archive for commercially interesting market structure before any live tender or DCE work.

Hard boundaries:

- no live discovery;
- no DCE/document retrieval;
- no bid/no-bid or FINAL_SUPER_GREEN decisions;
- no assumption that historical ease proves live eligibility;
- no currency mixing in market rankings;
- USAspending and AusTender remain award-first evidence, distinct from notice-first Global Core.

The lab reads the canonical upstream releases already used by `exhaustive-every-record-v1.yml` and produces derived historical intelligence only.

Current program:

1. exhaustive market-structure mining over every structured record;
2. native-code and title-signature cohort discovery without requiring a pre-existing SPM ontology;
3. buyer recurrence and supplier/winner concentration;
4. p25/median/p75 values and bidder evidence where available;
5. semantic QA of high-signal cohorts;
6. progressively build a durable commercial opportunity atlas.
