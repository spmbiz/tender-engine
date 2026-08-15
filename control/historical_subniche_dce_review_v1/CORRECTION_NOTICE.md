# Correction notice — Historical Sub-Niche DCE Reality Check v1

**Status: SUPERSEDED FOR GATE CLAIMS.**

The original v1 review reported 17 `gate_ready` candidates. Manual provenance QA later established that the downloaded French files used for those rows were BOAMP publication notice PDFs (`boamp.fr/telechargements/...pdf`), not the contracting authorities' consultation/DCE packages.

Those files are valid notice-level procurement evidence, but they are **not authoritative DCE evidence for mandatory-gate verification**. Therefore:

- do not use v1 `gate_ready=17` or its gate-prevalence percentages as DCE gate priors;
- do not infer references, turnover, staffing, insurance, certifications, onsite, subcontracting or other mandatory requirements from those v1 percentages;
- `pipeline/dce_evidence_quality.py` now deterministically classifies BOAMP publication PDFs as `NOTICE_ONLY / NOTICE_ONLY_NOT_DCE`, with `gate_readiness=false` when all retrieved files are notice PDFs;
- historical BOAMP gate research continues through `control/historical_boamp_dce_routes_v1/` and the downstream-route deep review v2;
- Quebec SEAO historical samples remain `AUTH_REQUIRED` in the public-access probe and are not bypassed.

This correction preserves the old outputs for auditability instead of silently deleting or rewriting history.
