# DCE Country Validation

Countries tested: **27**  
Real tender candidates: **302**  
Downloaded public DCE: **116** (38.4%)  
Downloaded or correctly stopped at legitimate gate: **158** (52.3%)

| Country | N | DCE | Gate | No public/route | Retryable | Retrieval | Handled | HTTP→no browser | Grade |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| CA | 12 | 4 | 0 | 8 | 0 | 33% | 33% | 0 | C |
| CA-QC | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| CH | 12 | 0 | 8 | 3 | 1 | 0% | 67% | 0 | D |
| CZ | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| DE | 11 | 0 | 0 | 11 | 0 | 0% | 0% | 0 | D |
| DK | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| EE | 12 | 12 | 0 | 0 | 0 | 100% | 100% | 0 | A |
| ES | 12 | 2 | 0 | 10 | 0 | 17% | 17% | 0 | D |
| FI | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| FR | 12 | 6 | 0 | 6 | 0 | 50% | 50% | 0 | B |
| GB | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| GB-SCT | 12 | 6 | 6 | 0 | 0 | 50% | 100% | 0 | B |
| GR | 12 | 12 | 0 | 0 | 0 | 100% | 100% | 7 | A |
| HR | 5 | 5 | 0 | 0 | 0 | 100% | 100% | 0 | A |
| IE | 12 | 10 | 0 | 0 | 2 | 83% | 83% | 0 | A |
| LU | 9 | 0 | 9 | 0 | 0 | 0% | 100% | 0 | D-GATED |
| LV | 12 | 2 | 10 | 0 | 0 | 17% | 100% | 2 | D-GATED |
| NL | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| NO | 12 | 1 | 9 | 2 | 0 | 8% | 83% | 0 | D-GATED |
| NZ | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| PL | 1 | 1 | 0 | 0 | 0 | 100% | 100% | 0 | A |
| PT | 12 | 12 | 0 | 0 | 0 | 100% | 100% | 12 | A |
| RO | 12 | 12 | 0 | 0 | 0 | 100% | 100% | 0 | A |
| SI | 12 | 0 | 0 | 12 | 0 | 0% | 0% | 0 | D |
| SK | 12 | 12 | 0 | 0 | 0 | 100% | 100% | 5 | A |
| US | 12 | 7 | 0 | 5 | 0 | 58% | 58% | 0 | B |
| ZA | 12 | 12 | 0 | 0 | 0 | 100% | 100% | 0 | A |

Notes:
- `DOWNLOADED_PUBLIC` requires at least one persisted file record in the candidate manifest.
- `LEGITIMATE_BARRIER` means the resolver reached an auth/CAPTCHA/registration/interest/controlled-document boundary and stopped rather than bypassing it.
- Small samples are marked medium/low confidence; this benchmark measures the current live corpus, not every tender ever published in the jurisdiction.
