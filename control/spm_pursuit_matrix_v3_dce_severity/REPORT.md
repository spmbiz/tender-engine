# SPM Pursuit Matrix v3 — DCE severity + business reality

This supersedes `spm_pursuit_matrix_v2_dce_grounded` for business prioritisation.

Authority inputs:
- `control/spm_hunt_subniches_v2_precision/`
- `control/historical_subniche_dce_review_v1/`
- `control/historical_gate_evidence_pack_v1/`
- `control/historical_gate_severity_v1/`
- `control/historical_boamp_dce_review_v2/`
- `control/historical_print_dce_business_brief_v1/`
- `control/germany_opendata_dce_recovery_v1/`
- `control/historical_market_priors.json`

Historical market facts decide what deserves live DCE compute. Historical DCE evidence is a blocker prior only. Every live opportunity remains UNKNOWN on mandatory gates until its own authoritative documents resolve them.

## Priority matrix

|Tier|Market / sub-niche|Motion|Historical open cohort|Median award|Competition evidence|DCE evidence|Observed hard-gate signals|SPM posture|
|---|---|---|---|---:|---|---|---|---|
|A1|France · Website maintenance / hosting / support|CORE DIGITAL|111 tenders / 103 buyers / 7 repeat|EUR 260k|top supplier 7.69%|3/3 gate-ready in primary review|references 3/3; security/data 1/3; one retrieved procurement had a mandatory Salesforce certification|HUNT NOW; kill stack-cert/security/ref gates first|
|A2|France · Municipal/public magazine printing|MICRO BROKER|138 / 130 / 8|broad cohort EUR 340k|broad fragmented market|1/3 primary sample gate-ready|severity: references 1/1, insurance 1/1; concrete job 4×3,000 copies, EUR 7–15k, 30-day payment, no financial guarantee, no imposed group form|HUNT NOW; excellent small broker archetype|
|A3|France · Written translation|AI + QUALIFIED HUMAN|63 / 59 / 4|EUR 190k|broad buyer base|2/3 gate-ready|references 2/2; mandatory-certification wording 1/2; one example technical 60 / price 40|HUNT NOW; separate completely from interpreting|
|A4|France · Website redesign / development|CORE DIGITAL|70 / 61 / 9|EUR 202.6k|broad buyer base|2/3 gate-ready|references 2/2; turnover/staffing can appear; AMO false-business-motion identified|HUNT NOW only genuine implementation; AMO bonus disabled|
|A5|France · Communication collateral printing|BROKER WITH DOSSIER|408 / 343 / 54|EUR 240k|top supplier ~1.09%|BOAMP v2: 2/2 downloaded + gate-ready|similar references; one sample had mandatory insurance + mandatory sample/proof/BAT; quantity + delivery signals|HUNT NOW; exact DCE → normalized multi-printer RFQ|
|A6|Germany · Website maintenance / support|CORE DIGITAL / LIVE-DCE FIRST|123 / 42 / 7|EUR 393k|median bidders 3.5; top supplier 4.76%|historical full DCE unavailable; official eForms route recovered for 2/9 exact-day samples|UNKNOWN historically; official eForms exposes external procurement-platform routes|HUNT LIVE NOW; use fresh DCE, do not infer historical gates|
|B1|France · Publication layout / DTP|CORE CREATIVE + PARTNER/DOSSIER|45 / 41 / 4|EUR 98.3k|fragmented|3/3 gate-ready|references 3/3; insurance mandatory 1/3; turnover minimum 1/3; staffing/equipment evidence appears; one award technical 65 / price 35|HUNT, but dossier readiness matters|
|B2|France · Meeting/debate transcription|AI + QUALIFIED QA|45 / ~42 / 3|~EUR 408k|specialist market|2/3 gate-ready|references 2/2; certification/authorization wording 1/2|HUNT only when qualified-human/QA model is resolved|
|B3|France · Brochure/publication/book printing|BROKER|historically material print lane|varies|fragmented parent market|BOAMP v2: 2/3 downloaded, 1 gate-ready|quantity/run + delivery + finishing observed|HUNT; exact specification first|
|B4|France · General graphic design|CORE CREATIVE|104 / 87 / 12|EUR 200k|top supplier 5.26%|1 gate-ready in primary sample; later BOAMP docs mostly non-gate-ready|no conservative hard wording detected in only gate-ready sample|HUNT, but eligibility sample remains thin|
|B5|France · Promotional objects / branded goods|BROKER|232 / 197 / 26|EUR 320k|fragmented|3/3 gate-ready primary sample|references 2/3; one market reserved to sheltered/social-integration operators; RSE/product-quality criteria matter|HUNT after reserved-participation kill switch|
|B6|France · General commercial print production|BROKER|557 / 445 / 78|EUR 380k|top supplier 1.24%|BOAMP v2 downloaded 2/2 sampled but 0 gate-ready|UNKNOWN mandatory gates in current sample|HUNT DCE-first; no generic margin assumptions|
|B7|France · Mailing / routing / fulfilment|BROKER|219 / 185 / 27|EUR 500k|top supplier 3.85%|current historical sample auth-gated/unresolved|UNKNOWN|HUNT DCE-first; GDPR/postal/storage/working-capital checks|
|W1|Québec · General commercial printing|BROKER / ACCESS-GATED|43 / 26 / 9|CAD 129.8k|median bidders 2; single-bid ~26% where covered|SEAO historical samples remain access/auth gated|UNKNOWN|HIGH LIVE DISCOVERY PRIORITY; never infer DCE gates from competition stats|
|W2|Canada federal · Written translation|AI + HUMAN|37 / 27 / 6|CAD 326.2k|bidder coverage unavailable|historical DCE unresolved|UNKNOWN|WATCH/HUNT selectively; credentials/security can dominate|
|HOLD|France · Human interpreting|HUMAN STAFFING|large demand|—|—|semantic lane clean after v2|staffing/on-site/language qualifications dominate|NO lean bonus|
|HOLD|France · Stenotypy / stenography|SPECIALIST HUMAN|31 clean title-led records|—|—|specialist-human gate|qualifications/on-site likely critical|NO lean bonus|
|HOLD|Canada · Interpretation/sign-language|SPECIALIST HUMAN|34 clean title-led records|—|—|staffing dependent|qualifications/language availability|NO lean bonus|
|HOLD|Ireland · broad survey / market research|—|—|—|—|semantic contamination survived QA|—|broad prior disabled|

## The five most actionable business plays

### 1. France municipal/public-magazine print brokerage
The strongest *small-business-shaped* historical DCE found so far is not the EUR 300k+ headline cohort. It is the repeatable municipal-magazine pattern: a buyer can require a few thousand copies several times per year, delivery included, with a contract small enough to quote across European printers. The recovered Champniers example was four editions of 3,000 copies and an estimated EUR 7k–15k. The same DCE had no financial guarantee and no imposed legal form for a bidder group, although the severity layer still found explicit references and insurance wording. This is the cleanest target for an automated `DCE → normalized RFQ → printer quotes → margin` engine.

### 2. France website maintenance / hosting / support
Historically attractive and supported by the best DCE coverage among digital lanes. The important correction is that it is **not** generic easy-money web work: references appeared in all three gate-ready DCEs, and technology-specific certification can be knockout. The harvester should therefore rank these highly, then run a very cheap stack/certification/reference prefilter before deeper proposal work.

### 3. France collateral print
This moved up materially after BOAMP DCE routing improved. Two of two newly recovered collateral-print samples were gate-ready. A real sample contained similar-reference, mandatory-insurance and mandatory sample/proof signals plus concrete quantity/delivery requirements. The market is historically extremely fragmented. This is brokerable, but SPM needs a reusable candidature pack and a proof/sample workflow — not merely cheap printers.

### 4. France written translation
The historical economics are attractive, but the real moat is quality evidence rather than raw AI output. References were explicit in both gate-ready historical DCEs; one of two carried mandatory-certification wording. The winning operating model is `AI draft / terminology tooling / professional human revision / controlled QA`, with interpreting kept out of this lane entirely.

### 5. Germany website maintenance/support
The market structure remains exceptional: EUR ~393k historical median, 3.5 median bidders in covered records, low winner concentration. Historical DCE files themselves were not recoverable, but the provenance problem is substantially solved: canonical `Official_Notice_ID` values can be mapped into official Publication Service eForms exports, and exact-day exports recovered external routes such as `deutsche-evergabe.de` and `evergabe-online.de`. The latter can require activating participation before downloading procurement documents, so expired historical files are a poor proxy for what is accessible while a tender is live. Therefore Germany stays **HUNT LIVE NOW / DCE FIRST**, not downgraded because old files expired.

## Gate-severity priors from the 17 authoritative historical DCEs

These are observed hard-wording signals, not universal rules:

- FR graphic design: n=1; no conservative hard wording detected.
- FR transcription: references **2/2**; certification-mandatory signal **1/2**.
- FR municipal/public magazine printing: references **1/1**; insurance-mandatory signal **1/1**.
- FR promotional goods: references **2/3**.
- FR DTP: references **3/3**; insurance mandatory **1/3**; turnover minimum **1/3**.
- FR website maintenance/support: references **3/3**; security/data hard signal **1/3**.
- FR website redesign/development: references **2/2**.
- FR written translation: references **2/2**; certification-mandatory signal **1/2**.

Absence is UNKNOWN, never a pass.

## Resolver / data-engine conclusions

1. **Historical DCE selector v2 is now canonical.** It understands `Warehouse_Source`, `Historical_Tender_ID`, canonical CPV/source URL fields and emits resolver-ready `portal`, `notice_url` and `route.detail_url`. The legacy selector path delegates to v2.
2. **BOAMP historical routing materially improved.** True print DCEs are now being recovered; do not use the earlier 0/3 print-DCE figures as authority.
3. **SEAO remains access-gated** in historical samples. Québec competition stats remain useful market priors, but historical DCE eligibility is unresolved.
4. **Germany provenance is repaired at the notice level.** `Official_Notice_ID` exists even when `Primary_Source_URL` is blank. The official `/api/notice-exports?pubDay=...` endpoint returns retrospective eForms ZIP exports; two exact-day samples matched and exposed external procurement-platform URLs. Historical document downloads remained unavailable/unresolved, which is consistent with expired participation/document access on external portals.
5. **Do not promote browser-only DE resolver v7 as a universal fix.** OpenData/eForms route recovery is the stronger architecture; the live route should use the current notice while documents are still available.

## Execution doctrine

1. Spend DCE compute on Tier A before breadth expansion.
2. Run knockout gates before economics: reserved participation → entity/geography → required certification/partner status → minimum turnover → mandatory references → named staffing/on-site → insurance/bond → deadline/submission.
3. Physical broker lanes: only estimate margin after exact DCE extraction and **2–5 normalized supplier quotes**.
4. Creative/language lanes: AI is production leverage, not evidence of experience and not a substitute for explicitly required qualified humans.
5. Build reusable candidature assets now: company presentation, insurance, turnover statements, standard subcontractor/cotraitance package, printer references, design portfolio/references, web references, translation/transcription human-QA partner evidence.
6. UNKNOWN remains UNKNOWN.
