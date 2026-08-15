# Tender Engine hard invariants

These rules are correctness constraints, not ranking preferences. A future refactor must preserve them.

## 1. Discovery is not qualification

`DISCOVERED` / `PRELIMINARY` candidates may be ranked for DCE effort, but no pre-DCE score may exceed 89 and no pre-DCE record may be called `FINAL_SUPER_GREEN`.

Discovery coverage is measured separately in `source_coverage.json`.

- `WORLD_COMPLETE` means every discovery lane configured by this engine for the run materialized cleanly.
- `PARTIAL_WORLD_COVERAGE` is still useful, but missing/degraded lanes must be disclosed.
- `WORLD_COMPLETE` never means every procurement authority on Earth was exhaustively enumerated.

## 2. Download success is not DCE success

`DOWNLOADED_PUBLIC` is a transport result only.

After extraction every retrieved corpus must pass `dce_evidence_quality.py` and receive:

- `content_quality`
- `derived_status`
- `gate_readiness`

Only `SUBSTANTIVE_DCE_PRESENT` or `MIXED_SUBSTANTIVE_AND_GUIDE` may become `gate_readiness=true`.

Examples that must remain gate-blocked:

- access/how-to guides;
- supplier-registration instructions;
- portal terms/CGU;
- an UNGM/WMO instruction file telling the supplier to click **Express Interest** / **View Documents**;
- empty downloads;
- unknown documents whose authority has not been established.

If public material says the supplier must first express/register interest to see the real documents, use `INTEREST_RECORDING_REQUIRED`; never treat the guide itself as the DCE.

## 3. No gate extraction from unverified material

`extract_gates.py` must return zero gate evidence when `gate_readiness=false`.

Absence of a keyword/snippet is never evidence that a requirement does not exist.

## 4. Canonical mandatory gates

Every final review must explicitly resolve all 14 gates:

1. `entity_geography`
2. `turnover_financial`
3. `references_experience`
4. `certifications_partner`
5. `staffing_team`
6. `insurance_bonds`
7. `subcontracting_consortium`
8. `deliverables_scope`
9. `sla_onsite`
10. `term_value`
11. `award_criteria`
12. `forms_signatures`
13. `submission`
14. `ip_data_security`

Allowed resolved states for a final green are:

- `PASS`
- `PASS_CONDITIONAL`
- `NOT_APPLICABLE`

`UNKNOWN` and `FAIL_HARD` block finalization. `PASS` / `PASS_CONDITIONAL` require evidence. `NOT_APPLICABLE` requires a reason.

`payment_tax` is also extracted as operational evidence but is not one of the 14 final-gate keys.

## 5. Authority conflicts are explicit

Metadata/feed dates may disagree with the procurement documents. Never silently overwrite one with the other.

`authority_conflicts.py` records the notice deadline, DCE deadline candidates, source context, and conflict state.

A deadline conflict or unresolved authoritative DCE deadline blocks a score >= 90 / `FINAL_SUPER_GREEN` until explicitly reconciled.

The same pattern should be extended to future conflicts for value, scope, lots, language, and term when reliable parsers are added.

## 6. Final verdict guard

`final_verdict_guard.py` is the last hard gate.

Any record attempting either:

- `score >= 90`, or
- `FINAL_SUPER_GREEN`

must have:

- authoritative DCE evidence (`gate_readiness=true`);
- an acceptable substantive `content_quality`;
- deadline authority resolved;
- all 14 gates resolved;
- evidence attached to every pass/conditional pass.

A downstream prompt or model output is not trusted merely because it says “green”. The guard is authoritative.

## 7. Durable evidence chain

Canonical DCE Release packs persist:

- original downloaded procurement files;
- `manifest.json`;
- extracted `corpus.txt` / document index;
- `evidence_quality.json`;
- `gate_snippets.json`;
- `authority_conflicts.json`;
- hashes and canonical pack manifest.

Actions artifacts are transport/convenience outputs, not the canonical store.

## 8. Dedupe semantics

Only exact/canonical identities may be destructively deduplicated. Title similarity alone must not destroy a candidate.

Known aliases (for example a TED notice and a national-portal copy) may be merged when the identity evidence is exact and provenance is preserved.

## 9. Access barriers are states, not failures to hide

Use explicit statuses such as:

- `AUTH_REQUIRED`
- `INTEREST_RECORDING_REQUIRED`
- `CAPTCHA_REQUIRED`
- `ROUTE_INCOMPLETE`
- `DCE_CONTENT_UNVERIFIED`
- `PORTAL_GENERIC_ONLY`
- `ERROR_RETRYABLE`

A barrier never becomes a green eligibility inference.

## 10. Regression contract

`Tender Pipeline Regression` must stay green before relying on a pipeline change. It includes a deliberate fake supergreen that the guard must reject.

`Tender Live Canary` exercises real WMO and COGG routes. The WMO 308742 path must never become gate-ready when only its access guide is retrieved; if COGG public DCE transport succeeds, its corpus must classify as gate-ready substantive evidence.
