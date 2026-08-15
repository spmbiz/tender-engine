# INVALIDATED — Broker/Resell run 31898918478

**Do not use this run for commercial decisions or downstream historical calibration.**

The workflow completed technically, but manual review of its ranked sample exposed two QA defects:

1. Country-scoped historical priors could fire when the live record omitted `country`, causing US SAM.gov records to receive unrelated France/Europe lane bonuses.
2. Broker lane matching inspected the full concatenated payload, allowing physical/medical procurements with incidental software-licensing text to enter the pure Software licences / SaaS resale lane.

Examples observed in the invalidated sample included a Steris ultrasonic irrigator, oxygen generation system, UV disinfection device, transmitter system and other physical procurements.

Corrections applied downstream:
- historical country rules now fail closed when country cannot be deterministically resolved;
- deterministic candidate-prefix country recovery added for known sources;
- Software/SaaS broker intent is title-anchored;
- physical/hardware/medical title collisions are excluded from the pure-software lane;
- US sole-source/non-bid/set-aside gates are applied before broker ranking.

Any DCE Fanout V2 run dispatched from this invalidated selection is diagnostic waste only and must not be promoted. A corrected broker scan supersedes it.
