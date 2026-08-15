# Atlas v3 — correction log

## Workwear / PPE short-token contamination

Atlas v3 row **#64 France — PPE / workwear** is temporarily **SUPERSEDED_PENDING_BOUNDARY_RERUN**.

Reason: semantic QA of the title-led precision census found that unbounded abbreviations created false matches:

- `EPI` matched inside French words such as `EPIC` / `EPICERIE`;
- `PPE` matched inside names such as `Kiltipper`.

The title-led standard-goods miner has been corrected to require word boundaries (`\bEPI\b`, `\bPPE\b`) and is being rerun. Until the corrected result is persisted, do not use the pre-boundary workwear/PPE counts as authoritative Atlas evidence.

Other Atlas v3 rows are unaffected by this specific short-token issue.
