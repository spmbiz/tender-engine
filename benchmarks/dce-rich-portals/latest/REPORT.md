# DCE Rich Portal Validation

Countries tested: **15**  
Real tender candidates: **217**  
Transport downloads: **31** (14.3%)  
Usable gate-ready DCE: **29** (13.4%)  
Usable or correctly stopped at legitimate gate: **72** (33.2%)

| Portal family | N | Transport | Usable DCE | Gate | Unresolved | Retryable | Transport % | Usable % | Handled % | HTTP→no browser | Grade |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| CA-CANADABUYS | 15 | 7 | 6 | 0 | 8 | 0 | 47% | 40% | 40% | 0 | C |
| CA-QC-SEAO | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| CH-SIMAP | 15 | 0 | 0 | 12 | 0 | 3 | 0% | 0% | 80% | 0 | D-GATED |
| DE-DOE | 14 | 0 | 0 | 0 | 14 | 0 | 0% | 0% | 0% | 0 | D |
| DK-UDBUD | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| FI-HILMA | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| FR-BOAMP | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| IE-ETENDERS | 15 | 12 | 11 | 0 | 1 | 2 | 80% | 73% | 73% | 0 | B |
| LU-PMP | 9 | 0 | 0 | 9 | 0 | 0 | 0% | 0% | 100% | 0 | D-GATED |
| NL-TENDERNED | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| NO-DOFFIN | 15 | 0 | 0 | 12 | 3 | 0 | 0% | 0% | 80% | 0 | D-GATED |
| NZ-GETS | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| UK-NOTICE-ROUTER | 15 | 0 | 0 | 0 | 15 | 0 | 0% | 0% | 0% | 0 | D |
| UK-SCOTLAND | 14 | 4 | 4 | 10 | 0 | 0 | 29% | 29% | 100% | 0 | C |
| US-SAM | 15 | 8 | 8 | 0 | 7 | 0 | 53% | 53% | 53% | 0 | B |

Notes:
- Transport means the resolver persisted at least one downloaded file.
- Usable DCE means production evidence-quality rules found substantive procurement material and proved candidate-document relevance.
- Auth/CAPTCHA/registration/interest/controlled-document boundaries count as legitimate barriers, never as downloads.
- This measures the current live corpus; it is not a claim that every tender ever published in the jurisdiction behaves identically.
