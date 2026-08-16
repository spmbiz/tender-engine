# GPT Web Supergreen Protocol

When the user asks **"supergreens?"**, **"what's live?"**, **"what can I bid?"**, or equivalent:

1. Read `control/gpt_supergreen_inbox.json` first. This is the canonical fast-answer surface.
2. Immediately report any live `confirmed_supergreens` already persisted there.
3. If `pending_final_review` contains rows with `recommended_gpt_action = FINAL_REVIEW_NOW`, adjudicate those rows from `evidence_by_gate` before searching logs/releases.
4. Never promote a Qwen label into a final verdict. Qwen is a pre-reader only.
5. `FINAL_SUPER_GREEN` requires authoritative DCE evidence for all potentially disqualifying mandatory gates and authoritative deadline reconciliation. Missing evidence is UNKNOWN, never PASS.
6. Never invent SPM Business turnover, references, staff, insurance, certifications, licences, manufacturer/reseller status, local establishment, or other bidder facts.
7. Persist completed GPT adjudications to `control/final_supergreen_bank.json`; the next Qwen-DCE aggregate will automatically remove resolved IDs from the pending inbox and expose confirmed live greens.
8. Do not let a newer empty DCE run erase older unresolved open candidates. Banks are persistent across runs; candidates disappear only when resolved, expired, or explicitly dropped.
9. Only inspect workflow logs/releases when the canonical inbox is stale, missing, or the user explicitly asks for pipeline diagnostics.

Canonical production path:

`live notices -> Qwen notice classification -> Qwen-specific DCE admission guard -> DCE retrieval/extraction -> Qwen DCE gate pre-read -> control/gpt_supergreen_inbox.json -> GPT Web final adjudication -> control/final_supergreen_bank.json`

The goal is that normal user-facing status requests are answered from one compact file rather than reconstructing state from GitHub Actions.
