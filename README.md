# Public Tender Intelligence — Lean Procurement Engine v1.9

This package adds `DCE_RESOLVER_V1` to the existing tender intelligence workflow.

The resolver is designed to turn procurement-document links into locally persisted, hashed DCE manifests that can be deep-dived before a tender is promoted to FINAL SUPER GREEN.

## Core flow

`notice -> extract official document URL -> portal adapter -> download -> recursive extraction -> manifest + SHA-256 -> qualification deep dive -> rescore`

## Safety / integrity

- No fabricated eligibility facts.
- UNKNOWN stays UNKNOWN.
- Login/MFA/CAPTCHA barriers return explicit non-success states.
- No FINAL SUPER GREEN score (90+) without verified final gates from the DCE or an equivalent authoritative source.

See `DCE_RESOLVER.md` and `LIVE_EXECUTOR.md` for the operating contract.
