# Super Green Hunt Runbook

## Why this exists

The Barnagh discovery run proved a useful pattern: broad live discovery + selective DCE retrieval + document reading can surface opportunities that ordinary notice-only scoring misses. This runbook captures that process so it is reproducible outside a single GPT conversation.

## The run that produced Barnagh

The actual sequence was roughly:

1. Exclude the already-known shortlist and prior hard rejects.
2. Search fresh live procurement sources instead of recycling MASTER rows.
3. Use bulk/structured discovery where available:
   - Ireland eTenders list pages / resource IDs
   - UK Contracts Finder OCDS
   - France PLACE consultation pages
   - targeted portal research for PCS and other current opportunities
4. Rank low-value / below-threshold / SME-friendly digital/creative opportunities.
5. For candidates that looked materially viable, retrieve the real DCE/RFQ rather than trusting notice summaries.
6. Unpack nested archives where required.
7. Read selection gates, scope, insurance, turnover, references, award criteria, deadline, and submission instructions.
8. Kill false greens immediately when the DCE exposed hard gates.
9. Promote only candidates whose mandatory gates and delivery burden remained viable.

Barnagh survived this process because the actual RFQ was unusually light on economic/technical selection barriers while the work stayed within a bounded digital/AR scope.

## Current source components in the repository

### Discovery

- `contracts_finder_fresh.py` — UK Contracts Finder OCDS harvesting/filtering.
- `etenders_scan.py` — lightweight Ireland discovery.
- `etenders_deep_scan.py` — deeper Ireland list-page scan.

### Portal routing

- `portal_routes.py` — portal family registry.
- `DCE_ROUTE_MATRIX.md` — validated routes, auth/captcha states, known fallbacks.

### DCE retrieval / portal probes

Examples currently include:

- `fresh_ireland_probe.py`
- `ireland_probe.py`
- `place_probe.py`
- `place_ref_probe.py`
- `pcs_probe.py`
- `lux_test.py`
- `ungm_probe.py`
- `procontract_probe.py`
- `evergabe_probe.py`

### Workflows

- `.github/workflows/fresh-hunt.yml`
- `.github/workflows/deep-scan.yml`
- `.github/workflows/uk-fresh.yml`
- `.github/workflows/place-fresh.yml`
- `.github/workflows/place-ref.yml`
- `.github/workflows/dce-resolver.yml`

## Current manual operating procedure

### 1. Start with a freshness exclusion set

Before discovery, materialize canonical IDs and titles that have already been:

- deeply analyzed
- rejected
- shortlisted
- expired

A fresh run must not spend browser/DCE budget on these unless explicitly rechecking an amendment.

### 2. Discover in breadth

Use official bulk interfaces first. Enumerate real records, not headline totals.

For each record capture:

- canonical source ID
- title
- buyer
- publication date
- deadline
- value/currency if available
- procedure type
- SME signal
- notice URL
- document URLs when exposed

### 3. Cheap-screen before DCE

Reject obvious misses. Keep the filter permissive enough to avoid missing creative/digital niches.

A practical initial score should reward:

- value <= 75k
- RFQ / quotation / below threshold
- public docs
- SME suitability
- web/design/video/content/software/AR/translation scope
- remote or bounded delivery

Do not give 90+ here.

### 4. Resolve exact portal route

Map the candidate through `portal_routes.route_for()` or a source-specific ref.

If the notice is an aggregator, follow the official buyer/eSender route before retrieving documents.

### 5. Retrieve procurement pack

Try public/anonymous routes first. Persist every file with SHA-256 and a manifest.

If the portal requires legitimate login, classify it and use an encrypted session only when configured. If CAPTCHA/MFA blocks retrieval, stop rather than bypassing it.

### 6. Unpack everything

Procurement packs frequently contain nested ZIP/7z archives. Recursively extract and inventory all files.

Do not assume the first PDF is the real tender brief; some portals expose generic submission guides alongside the actual DCE.

### 7. Read the gate documents first

Read in this priority order:

1. RFQ/RFT/instructions
2. selection questionnaire/ESPD
3. clarifications/FAQ
4. specification
5. terms and conditions
6. pricing schedule
7. award criteria

The first pass is not a summary. It is a **disqualification hunt**.

Search specifically for:

- turnover
- financial years
- accounts
- references/contracts/projects
- insurance
- professional indemnity
- employer/public/cyber liability
- certifications
- CVs/team
- language
- onsite
- location
- subcontracting/consortium
- tax clearance
- data/security
- SLA/support
- minimum qualitative score

### 8. Separate eligibility from execution

Produce two judgments:

- **Eligibility fit**: can this operator lawfully/credibly pass selection?
- **Delivery fit**: can the operator actually ship the work with AI/Codex/freelancers/subcontractors?

Example: Barnagh has light eligibility gates but some technical novelty; those are different risks.

### 9. Final score only after evidence

`SUPER_GREEN_VERIFIED` means the pack was read and no material mandatory gate remains unresolved.

If insurance/tax/reference wording is ambiguous, use `CONDITIONAL`, not a forced 90+.

## Evidence bundle expected for every promoted opportunity

A promoted candidate should have:

- canonical notice URL
- DCE source URL
- DCE manifest
- hashes
- extracted text location
- gate table
- delivery-fit note
- award criteria
- deadline/submission method
- final classification
- explicit blocker list

## Lessons from false positives in the same run

The fresh run also found attractive notices that failed after DCE review. This is expected and desirable.

Typical failure patterns:

- turnover gates far above the apparent project value
- 2–3 mandatory similar references
- high liability insurance limits
- mandatory local meetings/reporting
- combined creative + physical print/logistics lots
- hidden enterprise platform/support requirements

Therefore the success metric is not "number of notices that look green". It is **number of verified opportunities surviving DCE gates per unit of retrieval/reasoning time**.

## Immediate operating principle

Discovery should be broad and cheap. DCE retrieval should be selective but parallel. GPT reasoning should be reserved for candidates whose authoritative documents are already local and extracted.
