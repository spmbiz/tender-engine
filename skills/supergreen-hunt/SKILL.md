# Super Green Tender Hunt — Agent Skill

## Purpose

Find **new, currently actionable public procurement opportunities** that a very small AI-native digital operator can realistically bid and deliver, then verify the full procurement pack before promoting any opportunity to FINAL SUPER GREEN.

This skill is the authoritative operating contract for GPT/Codex/agent-assisted live tender hunting in this repository.

## Non-negotiable truth rule

**No opportunity may receive FINAL SUPER GREEN / score >= 90 until the DCE, RFQ, RFT, tender brief, or equivalent authoritative procurement pack has actually been retrieved and read for mandatory gates.**

UNKNOWN stays UNKNOWN. Do not infer eligibility from the notice title, CPV, estimated value, or marketing summary.

## Target operator profile

Optimize for a tiny Brussels-based, AI-native operator that can deliver or coordinate:

- websites / CMS / lightweight software
- WebAR / interactive digital experiences when technically bounded
- graphic design / layout / publishing / illustration
- video / animation / editing / AI-assisted visual production
- OCR / digitization / document workflows
- translation / transcription / localization
- dashboards / automation / lightweight integrations
- print brokerage only when operational and eligibility burden are lean

Deprioritize or reject:

- construction / heavy physical works
- large hardware procurement
- mandatory local workforce or frequent onsite presence
- impossible turnover / audited-account gates
- mandatory certifications not presently attainable
- enterprise support burden disproportionate to value
- large mandatory reference counts the operator cannot evidence
- controlled / restricted documents that cannot lawfully be accessed

## Freshness rule

A fresh hunt must exclude opportunities already materially analyzed, rejected, expired, or shortlisted in previous project runs unless explicitly performing a re-check.

Use canonical identifiers whenever available:

- TED publication number
- OCDS OCID / notice ID
- eTenders resourceId
- PCS notice reference
- PLACE consultation ID / procurement reference
- portal-specific tender ID

Do not count the same opportunity twice across aggregators or mirrors.

## End-to-end pipeline

### Stage 1 — Broad discovery

Run official/public bulk sources in parallel where possible.

Preferred sources include:

- TED Search API / eForms
- UK Contracts Finder OCDS
- UK Find a Tender
- Ireland eTenders
- Public Contracts Scotland
- France PLACE / BOAMP-compatible routes / AWS where lawful
- Luxembourg PMP
- UNGM
- Belgian e-Procurement
- TenderNed
- e-Vergabe
- Quebec SEAO open data
- CanadaBuys
- SAM.gov
- AusTender

Discovery is high-recall. It may use keyword / CPV / value / deadline / SME / procedure filters, but must not assign final eligibility.

### Stage 2 — Cheap screen

Reject obvious misses before browser-heavy work:

- expired deadline
- clearly out-of-scope physical work
- clearly excessive value/complexity when correlated with enterprise burden
- explicit domestic-only eligibility
- duplicate canonical ID
- already analyzed project ID

Rank remaining candidates using preliminary fit only.

Useful positive signals:

- below-threshold / RFQ / quotation
- SME-friendly
- low or moderate value
- remote delivery
- public documents
- design / web / video / content / software / automation scope
- short, bounded deliverables

### Stage 3 — Canonical notice resolution

Resolve the authoritative notice and buyer reference before document retrieval.

Never guess DCE URLs.

Use `portal_routes.py` and `DCE_ROUTE_MATRIX.md` to classify the portal and route.

### Stage 4 — DCE retrieval

Retrieve the actual procurement pack.

Order of operations:

1. direct/public document URL
2. anonymous portal adapter
3. exact-reference/title/buyer public mirror search
4. legitimate authenticated supplier session if required
5. stop and classify CAPTCHA/MFA/controlled access rather than bypassing it

Every successfully retrieved file must be persisted with:

- canonical opportunity ID
- portal
- source URL
- filename
- byte size
- SHA-256
- retrieval timestamp
- manifest status

Recursively unpack ZIP/7z archives where safe and lawful.

### Stage 5 — Document extraction

Extract text/tables from all relevant procurement files before GPT qualification.

Prioritize:

- instructions to tenderers / RFQ / RFT
- selection questionnaire / ESPD requirements
- terms and conditions
- specification / scope / deliverables
- pricing schedule
- award criteria
- clarifications / FAQ

Do not rely on a single document if the pack contains multiple files that can change eligibility.

### Stage 6 — Mandatory-gate analysis

For every candidate, explicitly resolve:

- turnover / financial capacity
- audited accounts requirements
- number / age / value / nature of references
- mandatory CVs / team size / named roles
- insurance types and minimum limits
- tax clearance timing
- certifications / accreditations
- language requirements
- geographic / onsite requirements
- subcontracting / consortium / reliance rules
- IP / licensing obligations
- hosting / SLA / support burden
- data protection / security requirements
- mandatory deliverables
- award criteria and minimum qualitative thresholds
- submission format and deadline

Each gate must be one of:

- PASS
- PASS_CONDITIONAL
- FAIL_HARD
- UNKNOWN
- NOT_APPLICABLE

### Stage 7 — Delivery-fit analysis

Separately assess whether the work can actually be shipped by the operator with AI, Codex, freelancers, subcontractors, or commodity tools.

Do not confuse legal eligibility with delivery ease.

Example: an opportunity can be legally easy to bid but technically novel; score those dimensions separately.

### Stage 8 — Final classification

Recommended classes:

- `SUPER_GREEN_VERIFIED` — >=90, DCE read, mandatory gates pass, delivery realistically bounded
- `GREEN_VERIFIED` — 80–89, DCE read, viable with manageable caveats
- `CONDITIONAL` — potentially attractive but one or more material gates unresolved
- `REJECT_HARD` — explicit disqualifying gate or unacceptable delivery burden
- `DCE_PENDING` — notice attractive but authoritative pack not yet read
- `AUTH_REQUIRED`
- `CAPTCHA_REQUIRED`
- `ERROR_RETRYABLE`

Never force a quota of Super Greens.

## GPT vs GitHub vs web-research responsibilities

### GitHub Actions / scripts

Use for deterministic, parallel, high-volume work:

- API/feed ingestion
- pagination
- canonicalization
- deadline filtering
- dedupe
- portal routing
- DCE downloads
- archive extraction
- hashing/manifests
- text extraction
- candidate queues

### GPT / reasoning agent

Use for high-value cognition after deterministic preprocessing:

- semantic fit
- interpretation of mandatory clauses
- cross-document contradiction resolution
- delivery architecture
- risk assessment
- final score/classification
- bid strategy

GPT should not manually browse hundreds of list pages when a script/API can do it.

### Web research

Use selectively for:

- official portal route discovery
- missing authoritative procurement pages
- buyer clarifications / amendments
- legal/tax/insurance questions
- exact-reference public mirrors

Do not use general web search as the primary high-volume discovery engine when official bulk interfaces exist.

## Parallelism contract

Parallelize by **independent unit of work**:

1. discovery source
2. portal family
3. candidate/DCE
4. document extraction
5. GPT qualification batch

Do not serialize independent portals inside one browser job.

Use bounded concurrency to avoid portal throttling. Default targets:

- API discovery: 4–12 concurrent requests per source, respecting source limits
- browser retrieval: 2–5 concurrent candidates per portal
- cross-portal GitHub matrix: one job per portal shard
- DCE text extraction: CPU-parallel where safe

## Queue contract

A candidate handed to the resolver should contain at minimum:

```json
{
  "candidate_id": "canonical-id",
  "source": "IRELAND_ETENDERS",
  "notice_url": "https://...",
  "title": "...",
  "buyer": "...",
  "deadline": "2026-08-17T10:00:00+01:00",
  "estimated_value": 50000,
  "currency": "EUR",
  "portal_key": "IRELAND_ETENDERS",
  "portal_ref": "8670172",
  "pre_score": 78,
  "fresh": true
}
```

Resolver output must add evidence/status rather than overwrite unknowns with guesses.

## Throughput reporting

Every run must report real counts:

- raw records enumerated
- canonical unique
- cheap-screen rejects
- fresh candidates
- candidates queued for DCE
- DCE retrieval successes
- DCE retrieval gated/errors
- DCEs fully extracted
- hard rejects after DCE
- conditional opportunities
- verified greens
- verified Super Greens
- elapsed time per stage / portal

Never report dataset headline totals as processed records unless identities were materially enumerated.

## Stop condition

A hunt may stop when:

- the requested workload floor is complete, or
- sources are exhausted, or
- a legitimate terminal blocker is proven.

Do not stop merely because the first attractive candidate was found.
