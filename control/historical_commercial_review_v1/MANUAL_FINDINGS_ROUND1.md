# Historical Commercial Miner — Manual Findings Round 1

Scope: **historical structured evidence only**. No live tenders and no DCEs are used here. These are business-model hypotheses to investigate further, not live eligibility conclusions.

## Strong new investigation lanes

### 1. Australia — ICT labour hire / temporary personnel brokerage

Empirical cohorts from the award-first AusTender archive:

- `ICT labour hire` — 667 records, 6 buyers, 4 repeat buyers, median award AUD 619,413.96, 169 suppliers, top-supplier share 4.5%.
- `temporary personnel services` — 68 records, 3 buyers, median AUD 752,444, 47 suppliers, top-supplier share 7.4%.
- `business analyst` — 14 records, 5 buyers, 4 repeat buyers, median AUD 647,741.60, 12 suppliers, top-supplier share 14.3%.
- several `project/program management services` cohorts also recur with dozens of suppliers and median awards around AUD 0.8m–1.4m.

**Hypothesis:** this is materially more fragmented than many product/platform markets and could support an agency/broker model based on sourcing contractors rather than performing all work internally.

**Do not infer:** open tender access, panel eligibility, labour-law feasibility, security clearance requirements, local entity requirements, or SPM live eligibility. AusTender here is award-first evidence only.

**Decision:** `INVESTIGATE_STAFFING_BROKER_MODEL`.

### 2. Sweden — consultant brokerage (`Konsultmäklare`)

Global Core notice-first cohort:

- 3 recurring procurements across 3 buyers under code 72000000.
- Historical examples include E-hälsomyndigheten, Sigtuna kommun, and Almi AB.
- Recorded values in the cohort: roughly SEK 400m, 517m, and 1.15bn.

**Hypothesis:** the buyer is explicitly procuring a consultant-broker/aggregator function, which is structurally close to a middleman model rather than a traditional delivery shop.

**Caveat:** the very large framework values likely imply scale, framework-management, financial, and supplier-network burdens. The large headline value should not be treated as attainable SPM revenue.

**Decision:** `INVESTIGATE_CONSULTANT_BROKER_MODEL`.

### 3. Australia — software support / development / licence + maintenance

Empirical award-first cohorts:

- `software support services` — 19 records, 4 buyers, median AUD 772,997.56, 12 suppliers, top share 21.1%.
- `software development services` — 5 records, 3 buyers, median AUD 2.30m, 5 suppliers, top share 20%.
- `software development` — 6 records, 2 repeat buyers, median AUD 4.11m, 5 suppliers, top share 33.3%.
- `software licence and maintenance` — 4 records, 3 buyers, median AUD 6.22m, 4 suppliers, top share 25%.

**Hypothesis:** software resale/support remains worth decomposing into vendor-specific resale vs implementation/support vs custom development. Historical award size is attractive, but reseller/partner and panel gates are unknown.

**Decision:** `INVESTIGATE_SOFTWARE_SUBLANES`.

### 4. Australia — data services

- 11 records, 2 buyers, median AUD 1.382m, 9 suppliers, top share 18.2%.

**Hypothesis:** potentially attractive if the underlying work includes data processing, datasets, analytics, migration, cleansing, enrichment, or managed data services rather than classified/specialist defence work.

**Decision:** `DECOMPOSE_DATA_SERVICES`.

### 5. Germany — postal delivery of official notices

Global Core notice-first cohort:

- `Rahmenvereinbarung über die Zustellung von Bescheiden mittels Postzustellungsauftrag`.
- 3 records, 2 buyers, repeat buyer present, open-public route, observed median around EUR 12.0m.

**Hypothesis:** fulfilment/mail-routing is a real repeated procurement family beyond printing itself. Could be commercially interesting as a broker/fulfilment lane, but postal licensing/network economics and incumbent advantage may dominate.

**Decision:** `INVESTIGATE_POSTAL_FULFILMENT`, not promoted.

### 6. Finland — cleaning/consumable supplies

Global Core notice-first cohort `Puhtaanapidon tarvikkeet`:

- recurring supply procurements, observed values in the multi-million EUR range.

**Hypothesis:** standardized consumables can be brokerable and should not be discarded merely because they are non-digital. Need a broader native-code decomposition before judging margins or supplier concentration.

**Decision:** `INVESTIGATE_STANDARD_GOODS_BROKERAGE`.

## Interesting but currently weak / likely hold

### Employee Assistance Program — Québec

17 open-public notices across 15 buyers under the normalized wording `Programme d'aide aux employés`; a real multi-buyer market. Delivery likely requires a professional provider network and possibly regulated clinical services. Could be brokerable through an established EAP subcontractor, but not a lean-core service.

Decision: `HOLD_FOR_DELIVERY_MODEL`.

### Australia media buying

11 records / 5 buyers / median AUD ~6.57m, but the empirical cohort has **1 supplier and 100% top-supplier share** in the linked historical data.

Decision: `HOLD_CONCENTRATION` despite attractive headline values.

### Large public frameworks / health / construction / energy

The highest market-structure scores frequently represent enormous framework values, regulated healthcare, infrastructure, energy, or highly specialized services. High score means recurring historical market structure, **not SPM feasibility**.

Decision: keep in archive atlas but do not promote merely for size/low observed bidder count.

## Methodological finding

The previous open-world clustering was too vulnerable to contract-number signatures (especially AusTender) and to low-bidder R&D/SBIR awards in USAspending. The new raw miner materially improves this by joining buyer recurrence and fractionalized supplier concentration and by carrying representative source titles. Manual semantic QA remains mandatory before a cohort is called commercially promising.
