# AGENTS.md — Local LLM Cascade Direction

## Strategic direction

This repository should add a **hybrid deterministic + local small-LLM qualification layer** so that broad tender discovery can be filtered semantically at very high volume before expensive GPT/DCE reasoning.

The intended role of local models is triage, extraction and confidence routing — **not final legal/commercial judgment** and not a replacement for authoritative DCE verification.

Target architecture:

```text
broad official discovery
  -> normalize / dedupe / hard rules / CPV filters
  -> ultra-cheap semantic prefilter (optional sub-1B model)
  -> small local 3B–4B instruct classifier
  -> confidence router
      -> obvious reject / plausible keep
      -> ambiguous cases -> stronger GPT semantic read
      -> shortlisted candidates -> DCE retrieval
      -> authoritative mandatory-gate deep read
      -> final GREEN / SUPER GREEN decision
```

This must preserve the repository's existing law that no FINAL SUPER GREEN score is granted without mandatory-gate evidence from authoritative procurement material.

## Primary tender use case

Use a small local model to decide whether a notice plausibly fits the capabilities we can actually deliver or broker, from compact inputs such as:

- title;
- short description;
- CPV/category codes;
- buyer;
- country;
- estimated value if present;
- lot descriptions;
- short extracted snippets.

Example capability families currently relevant include:

- website / CMS / web redesign / digital platform work;
- software / lightweight automation / AI-enabled implementation;
- transcription / language-processing work;
- graphic design / creative production;
- video / AI-assisted media production;
- printing / print brokerage / fulfillment where subcontracting is viable.

Desired strict output shape:

```json
{
  "decision": "STRONG_FIT|FIT|MAYBE|REJECT",
  "confidence": 0.0,
  "matched_capabilities": [],
  "possible_blockers": [],
  "needs_dce": true,
  "reason": "short explanation"
}
```

The classifier must never invent eligibility, budget, certifications, submission rules or buyer requirements. UNKNOWN is valid.

## What local models should do

Good tasks for 3B–4B local models:

- semantic niche classification beyond simple keywords;
- detect that procurement language is conceptually equivalent to one of our niches;
- rank notices for GPT attention;
- identify obvious unrelated tenders;
- extract structured fields from already-retrieved text;
- tag likely subcontractable components;
- identify which notices merit DCE download first;
- summarize small chunks into compact handoff JSON.

## What local models should NOT own

Do not trust a lightweight model alone for:

- final legal eligibility;
- mandatory certifications;
- bid/no-bid on ambiguous contractual obligations;
- interpreting contradictory DCE clauses;
- final pricing feasibility;
- final GREEN/SUPER GREEN scoring;
- assertions not present in source material.

Those remain for deterministic verification, authoritative document evidence and stronger-model review.

## Model/runtime preference

Optimize first for CPU-friendly GGUF inference under `llama.cpp` on free/ephemeral GitHub-hosted runners.

Candidate families to benchmark rather than permanently hard-code:

- Qwen 3/3.5 class ~3B–4B instruct models;
- Phi-4-mini class ~3.8B;
- SmolLM3 ~3B;
- sub-1B Qwen-class model only as a garbage pre-filter.

Prefer 4-bit quantization when workload accuracy remains acceptable. Keep prequalification prompts compact; do not feed whole DCEs into a small model merely because a large context window is advertised.

## Suggested multi-stage funnel

A practical target is:

```text
100,000 raw notices
  -> deterministic source/category/CPV/rule filters
  -> 10,000–30,000 plausible textual candidates
  -> local small-LLM semantic classification
  -> 1,000–5,000 high-value candidates
  -> stronger GPT wide-read
  -> narrow DCE queue
  -> DCE retrieval + authoritative gate extraction
  -> final deep review
```

Exact volumes must be measured; do not fake throughput targets by silently lowering quality.

## GitHub Actions / fleet integration

When implementing:

- use independent shards compatible with the existing autonomous fleet;
- avoid every short-lived runner re-downloading multi-GB weights when possible;
- use GitHub cache, durable cached artifacts where appropriate, or a shared inference endpoint if that is cheaper/faster;
- preserve fail-safe durable outputs before worker exit;
- local-model failure should return an explicit state and must not consume/lose the candidate;
- do not introduce concurrent writes to shared canonical files;
- preserve current Release-based durability and lease semantics;
- benchmark CPU inference under actual `ubuntu-latest` constraints before increasing fanout.

CircleCI workers may use the same classifier contract if model/runtime caching makes sense there.

## Required benchmark before production routing

Build a labeled **AI PROD tender benchmark** from real previously reviewed notices.

Suggested first set: 300–1,000 notices covering obvious rejects, semantic fits, misleading keyword matches, borderline cases and genuine high-value opportunities.

Compare candidate local models against trusted GPT/human labels and track:

- precision on FIT/STRONG_FIT;
- recall on known good tenders;
- false-negative rate on GREEN/SUPER-GREEN-like opportunities (critical);
- false-positive reduction versus keyword/CPV rules;
- ambiguity rate;
- latency per notice;
- peak RAM;
- notices/minute per runner;
- model download/cache overhead.

Optimize for **cost and compute per retained true opportunity**, not generic benchmark scores.

## Implementation philosophy

1. **Deterministic first.** Source metadata, CPVs, deadlines, hashes and exact gates belong in code.
2. **Small LLM second.** Use it for semantic ambiguity and language mapping.
3. **Stronger GPT only where valuable.** Do not spend frontier-model reasoning on obvious garbage.
4. **Confidence router.** Never make a single small-model score an unreviewable truth.
5. **Strict structured output.** Machine decisions should be JSON-schema validated.
6. **Source-grounded only.** No fabricated tender facts.
7. **Preserve the DCE final gate.** Lightweight preclassification can prioritize retrieval, never bypass authoritative verification.
8. **Incremental rollout.** Shadow-score first, benchmark, then enable automatic rejection only at empirically safe thresholds.

When agents modify the discovery, wide-read handoff, queueing or autonomous-fleet paths, they should actively consider whether this local-LLM cascade can remove unnecessary GPT workload while preserving or improving recall of genuine high-value tenders.