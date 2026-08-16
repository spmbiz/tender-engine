---
name: tender-engine
description: Operate the SPM Business public-tender intelligence engine end to end: high-recall discovery, Qwen semantic triage, selective DCE retrieval, Qwen DCE pre-read, mandatory-gate verification, durable preservation, and instant GPT Web bid/no-bid answers.
---

# Tender Engine — Canonical Operating Skill

## User-facing contract: answer supergreens instantly

When the user asks **“supergreens?”**, **“what’s live?”**, **“what can I bid?”**, **“rapport”**, or an equivalent current-opportunity question:

1. Fetch `control/gpt_supergreen_inbox.json` from `walidgdg1-ai/tender-engine` **before reconstructing workflow state**.
2. Report live `FINAL_SUPER_GREEN` and `GREEN` entries immediately.
3. Mention `YELLOW` only when it helps explain a partner/consortium route or a near miss.
4. If `pending_final_review` contains `FINAL_REVIEW_NOW`, adjudicate those rows from their authoritative `evidence_by_gate` before searching Actions logs.
5. Persist completed GPT verdicts in `control/final_supergreen_bank.json`.
6. Only inspect Actions logs/releases when the canonical inbox is stale/missing, when pending evidence needs deeper source material, or when the user explicitly asks for pipeline diagnostics.
7. Never let an empty/new run erase older open unresolved or resolved live candidates.

The normal answer surface is **one compact file**, not a reconstruction job.

## Canonical production path

**LIVE NOTICES → QWEN NOTICE CLASSIFICATION → QWEN-SPECIFIC DCE ADMISSION GUARD → SELECTIVE DCE → EXTRACTION/GATES → QWEN DCE PRE-READ → GPT INSTANT INBOX → GPT WEB FINAL ADJUDICATION → FINAL BANK**

- Qwen3-4B GGUF is a local high-volume semantic pre-reader. It is not an eligibility authority.
- Qwen may classify notices and gate-ready DCE evidence, but **Qwen never creates `FINAL_SUPER_GREEN`**.
- GitHub Actions must not depend on an OpenAI API key for the production DCE/adjudication path.
- GPT Web is the final semantic adjudicator over authoritative DCE evidence.

## Mission

Find public tenders SPM Business can fulfill leanly through AI, software, direct digital delivery, subcontracting, consortium, resale, brokerage/middleman execution, or other low-fixed-cost models. Optimize for expected profit, feasibility, low friction and speed without destroying open-world recall.

## Evidence invariants

1. Missing evidence is **UNKNOWN**, never assumed satisfied.
2. Never label `FINAL_SUPER_GREEN` or score 90+ until all potentially disqualifying mandatory gates are resolved from authoritative DCE/equivalent evidence.
3. Notice evidence can rank a candidate but cannot finalise turnover, references, certifications, staffing, insurance, submission, subcontracting or delivery eligibility.
4. Never invent SPM Business turnover, references, staff, insurance, certifications, licences, geographic establishment or manufacturer/reseller status.
5. Historical competition is a prior, not proof of live ease.
6. Software/licensing/cloud/cyber/hardware/AV carry partner/reseller risk until documents resolve it.
7. Do not bypass authentication, CAPTCHA, MFA or controlled attachments.
8. Preserve authoritative IDs/provenance and exact identity; do not destructively fuzzy-dedupe.
9. Do not mix currencies without sourced FX normalisation.

## Mandatory DCE gates

Before `FINAL_SUPER_GREEN`, resolve as applicable:

- entity/geography;
- turnover/financial ratios;
- references/experience;
- certifications/manufacturer/reseller status;
- staffing/CVs;
- insurance/bonds;
- subcontracting/consortium/reliance;
- deliverables/volumes;
- SLA/on-site/local presence;
- term/options/value;
- award criteria;
- forms/signatures;
- submission channel, authoritative deadline and language;
- IP/source files/data/security;
- payment/tax requirements.

Store decisive snippets and source provenance.

## Deadline authority

Treat query/clarification deadlines separately from tender/bid/request-to-participate submission deadlines. Only a date locally bound to authoritative submission language can automatically resolve bid timing. A query date must never be presented as the tender deadline.

## Final classes

- `FINAL_SUPER_GREEN`: mandatory gates resolved; exceptional economics/feasibility; live authoritative deadline.
- `GREEN`: feasible and attractive but not exceptional, or bidder-side proof still needs confirmation without a discovered hard blocker.
- `YELLOW`: promising but material qualification, partner, operational or evidence risk.
- `RED`: hard blocker, incompatible requirement, closed/expired, or bad economics.
- `UNKNOWN/PENDING_DCE`: insufficient authoritative evidence.

## Qwen notice layer

Use local Qwen for high-volume notice classification (`STRONG_FIT`, `FIT`, `MAYBE`, `REJECT_OBVIOUS`) plus lean, delivery route, friction, `KEEP/DROP`, and DCE eligibility. `KEEP` is not `FIT`.

The expensive DCE layer must not accept a Qwen label blindly. `pipeline/materialize_dce_selection.py` checks real notice content for SPM core relevance and keeps a bounded deterministic exploration lane for open-world recall.

## Qwen DCE layer

For gate-ready DCE corpora, local Qwen performs a bounded pre-read of compact evidence and emits only routing classes such as `QWEN_DCE_HOT/GOOD/MAYBE/BLOCKED/INSUFFICIENT` plus `FINAL_REVIEW_NOW` or lower-priority actions.

Qwen DCE output is **pre-read only**. A model-only HOT/GOOD cannot survive without packed authoritative gate evidence. Non-core/heavy scopes must not enter the user-facing inbox merely because the model is optimistic.

## Persistence / self-healing

- Canonical user inbox: `control/gpt_supergreen_inbox.json`.
- Canonical GPT final decisions: `control/final_supergreen_bank.json`.
- Latest Qwen DCE pre-read: `control/qwen_dce_triage_latest.jsonl`.
- Durable DCE packages: GitHub Releases `dce-harvest-<run_id>`.
- Persisted DCE manifests are retried by queue drainers when capacity is temporarily unavailable.
- Qwen DCE triage has a self-healing drainer that finds durable DCE releases lacking a Qwen pre-read.
- Cleanup is copy → verify → only then delete temporary duplicates. Never delete unique harvested/DCE evidence to save Actions storage.

## Selective DCE

Do not fetch DCE for the whole universe. Use high-recall discovery/Qwen first, then spend DCE workers on the best or deliberately exploratory candidates. Curated GPT/SPM shortlists may use a small bounded free-slot latency lane but may never preempt running workloads or exceed physical runner capacity.

## Working style

On “go”, “continue”, “check”, “mtn”, or “rapport”, execute the highest-value unfinished step without re-asking known constraints. For current status, live-fetch GitHub first. Report business output, not just CI health.

When a bottleneck is measured, fix the bottleneck rather than merely adding compute.
