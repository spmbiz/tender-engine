# Historical Semantic Verdicts v1

Scope: historical structured evidence only. These verdicts adjudicate the **meaning of historical cohorts**, not current eligibility, profitability, or bidability.

## PROMOTE — semantically supported market families

### Office stationery / bureau supplies

**PROMOTE_STANDARD_GOODS_BROKERAGE**

Representative-title QA is clean in the largest markets reviewed.

- France: 1,316 records; 1,019 buyers; 207 repeat buyers; median EUR 300k; 310 linked suppliers; top supplier 3.6%. Examples are office supplies, stationery, copy paper, school/office supplies and related small-office equipment. Historical winners include Lyreco, Fiducial, Inapa, Lacoste and Antalis.
- Germany: 509 records; 126 buyers; 13 repeat; median EUR 266,050.42; 46 suppliers; top supplier 17.5%. Examples are office-consumable and office-material framework agreements.
- United Kingdom: 70 records; 62 buyers; 7 repeat; median GBP 350k; 108 linked suppliers; top supplier 16.2%. Examples are office supplies / paper / EOS frameworks.
- Québec: 47 records; 23 buyers; 13 repeat; median CAD 57,731.12; 29 suppliers; top supplier 8.9%. Representative titles are clean bureau/papeterie procurements.

The huge framework headline values are not interpreted as attainable SPM revenue. Margin and distributor pricing are not known from award values.

### Germany — standard furniture

**PROMOTE_STANDARD_GOODS_BROKERAGE**

- 698 records; 235 buyers; 34 repeat buyers; median EUR 321,455.21; 170 linked suppliers; top supplier 4.5%.
- Representative titles are office furniture, loose furniture/interior items, and office-furniture framework supply, sometimes including normal assembly.

This is a genuine catalogue/distribution market. Installation-heavy furniture should remain separately flagged.

### France — PPE / workwear

**PROMOTE_WITH_SERVICE_MIX_CAVEAT**

- 1,052 records; 849 buyers; 152 repeat; median EUR 240k; 336 suppliers; top supplier 2.0%.
- Representative titles are workwear, uniforms, PPE and associated supply. Several include rental/maintenance/laundry, so this is not a pure catalogue-goods lane.

Split future analysis into outright supply vs rental/laundry/managed workwear.

### Travel management agency

**PROMOTE_AGENCY_INTERMEDIARY**

Broad-broker semantic QA shows this is a real agency category rather than regex noise.

- France: 261 notices; 226 buyers; 30 repeat; median EUR 683,333; 53 suppliers; top supplier 14.3%.
- Québec: 22 notices; 14 buyers; 4 repeat; median CAD 83,731.36; 14 suppliers; top supplier 14.3%.
- United Kingdom: 20 notices; 17 buyers; 2 repeat; median GBP 8m; 7 suppliers; top supplier 25%.
- Norway is much more concentrated historically and should be held separately.

Delivery requires real travel-agency/ticketing infrastructure; promotion here means historical business-model significance, not SPM readiness.

### UK / Ireland — media buying agency

**PROMOTE_AGENCY_INTERMEDIARY**

- UK: 170 notices; 136 buyers; 26 repeat; median GBP 1,516,667; 132 linked suppliers; top supplier 8.4%. Representative titles are media planning/buying campaigns and agency frameworks.
- Ireland: 16 notices; 15 buyers; 1 repeat; median EUR 425k; 11 suppliers; top supplier 11.1%.

This is a real, historically fragmented agency market. Media-buying working capital, credit terms and platform/agency credentials remain separate business-model questions.

### UK — ICT value-added reseller

**PROMOTE_RESELLER_ECOSYSTEM_WITH_FRAMEWORK_RISK**

- 17 historical notices; 14 buyers; 2 repeat; median GBP 135m; 15 linked suppliers; top supplier ~15.4%.
- Representative titles explicitly include ICT Value Added Reseller / Software VAR frameworks.
- Historical winners include Softcat, XMA, CDW and Boxxe.

The giant framework values imply scale and framework risk; this is evidence the reseller market exists, not that it is lean-entry accessible.

### UK — freight forwarding / logistics agency

**PROMOTE_MODEL_FOR_FURTHER_ANALYSIS**

- 10 notices; 10 buyers; median GBP 1m; 12 linked suppliers; top supplier ~18.2%.
- Representative titles explicitly include freight forwarding/logistics services.

This is a genuine intermediary/logistics model, but customs, freight-network, insurance and working-capital requirements likely dominate execution.

## HOLD — real markets but specialist/regulatory/local constraints dominate

### Insurance brokerage

`HOLD_REGULATED`

Historical cohorts are semantically real, but insurance brokerage is regulated and often concentrated. Ireland examples are dominated by major brokers such as Marsh/WTW. Do not treat as a lean SPM lane without licensing/partner strategy.

### Real-estate brokerage

`HOLD_LOCAL_REGULATED`

Historical brokerage cohorts are real in Canada, UK, Germany, Québec and other markets, but local licensing, property-market presence and geography are material.

### Sweden — consultant broker

`HOLD_SCALE_FRAMEWORK`

Semantically real and strategically interesting, but historical values are very large and supplier concentration is materially higher than France staffing/Australia ICT talent. Keep as explicit middleman-market evidence, not entry priority.

### Norway — travel management

`HOLD_CONCENTRATION`

Market is semantically real but historical top-supplier concentration is ~84% in the reviewed NOK bucket.

## REJECT / RECLASSIFY — regex cohorts that are not the claimed business family

### France — `ICT_HARDWARE_VAR`

**REJECT_FALSE_POSITIVE**

The broad census matched `Var`, the French département, not "Value Added Reseller". Representative titles include public works, electricity, heating and infrastructure in the Var. Do not use this bucket as ICT reseller evidence.

Similar short-token `VAR` contamination exists in some Lithuanian/Romanian results and must not be promoted without exact semantic evidence.

### France — `PROCUREMENT_AGENT`

**REJECT_AS_BUSINESS_FAMILY**

Representative titles primarily describe supplies/services procured **for members of a centrale d'achat**. The supplier is not being hired to act as a procurement agent. These are normal framework purchases by a central purchasing body.

The UK corpus contains isolated genuinely named procurement-agent work, but the broad family is not a valid promotion cohort.

### France — broad `PACKAGING`

**HOLD_QA / NARROW_REQUIRED**

Representative titles are heavily contaminated by waste collection, recycling and treatment of packaging. Do not promote the broad family. Future analysis must require actual packaging-material supply terms.

### France — broad `SIGNAGE_STANDARD`

**HOLD_QA / NARROW_REQUIRED**

Many representative titles include construction/project signage and broader works. Future analysis should separate simple signage manufacture/supply from fabrication+installation tied to construction.

### UK — broad `IT_PERIPHERALS`

**HOLD_QA / NARROW_REQUIRED**

The current broad title/scope matcher includes giant technology frameworks and unrelated medical/equipment procurements. The underlying peripherals market is likely real, but this cohort is not clean enough for promotion without a stricter product classifier.

## Methodological consequence

Short ambiguous tokens and scope-wide keyword matching can create commercially dangerous false cohorts. Atlas promotion now requires representative-title QA for new broad families. Record count, buyer count, value and low supplier concentration are insufficient if the semantic family itself is not clean.
