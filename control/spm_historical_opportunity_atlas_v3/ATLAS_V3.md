# SPM Historical Opportunity Atlas v3

**Scope: historical structured evidence only. No live tender, no DCE, no current bidability inference.**

Atlas v3 inherits the 57 evidence-backed lanes in `control/spm_historical_opportunity_atlas_v2/ATLAS_V2.md` and adds only semantically reviewed historical markets from the standardized-goods and explicit-broker censuses.

**Total historical lanes tracked in v3: 76.**

The numbering below continues v2. `NOTICE_FIRST` can support historical tender/competition structure where source evidence exists; `AWARD_FIRST` supports historical demand/supplier structure but never implies open-bid ease. Currencies remain separate.

## New promoted / investigate lanes

| # | Market | Grain | Historical structure | Native value | Supplier structure | Historical business-model verdict |
|---|---|---|---|---|---|---|
| 58 | France — office stationery / bureau supplies | NOTICE_FIRST | **1,316 records · 1,019 buyers · 207 repeat buyers** | median **EUR 300k** | **310 suppliers · top 3.6%** | **PROMOTE_STANDARD_GOODS_BROKERAGE** — representative titles are office supplies, stationery, paper and small office equipment |
| 59 | Germany — office supplies | NOTICE_FIRST | **509 · 126 buyers · 13 repeat** | median **EUR 266,050.42** | **46 suppliers · top 17.5%** | **PROMOTE_STANDARD_GOODS_BROKERAGE** — clean office-material framework examples |
| 60 | United Kingdom — office supplies / paper / EOS | NOTICE_FIRST | **70 · 62 buyers · 7 repeat** | median **GBP 350k** | **108 linked suppliers · top 16.2%** | **PROMOTE_STANDARD_GOODS_BROKERAGE**; very large national frameworks should not be read as attainable SPM revenue |
| 61 | Québec — office supplies / papeterie | NOTICE_FIRST | **47 · 23 buyers · 13 repeat** | median **CAD 57,731.12** | **29 suppliers · top 8.9%** | **PROMOTE_STANDARD_GOODS_BROKERAGE** — semantically clean municipal/public examples |
| 62 | Belgium — office supplies | NOTICE_FIRST | **78 · 65 buyers · 9 repeat** | value evidence UNKNOWN in current bucket | supplier linkage UNKNOWN | **WATCH_STANDARD_GOODS** — titles are clean office-supply procurements; economics need stronger linked evidence |
| 63 | Germany — standard office/school furniture | NOTICE_FIRST | **698 · 235 buyers · 34 repeat** | median **EUR 321,455.21** | **170 suppliers · top 4.5%** | **PROMOTE_STANDARD_GOODS_BROKERAGE**; normal delivery/assembly appears, heavy installation must stay separated |
| 64 | France — PPE / workwear | NOTICE_FIRST | **1,052 · 849 buyers · 152 repeat** | median **EUR 240k** | **336 suppliers · top 2.0%** | **PROMOTE_WITH_SERVICE_MIX_CAVEAT** — workwear/PPE supply is real, but rental/laundry/maintenance must be split from outright supply |
| 65 | Germany — paper / envelopes / print-mail supplies | NOTICE_FIRST | **361 · 118 buyers · 31 repeat** | median **EUR 322,717.50** | **57 suppliers · top 6.8%** | **PROMOTE_DOCUMENT_SUPPLY_FULFILMENT** — representative titles include envelopes, paper, print/insert/post services |
| 66 | Québec — signage manufacture / supply / install | NOTICE_FIRST | **92 · 57 buyers · 19 repeat** | median **CAD 55,626.63** | **50 suppliers · top 9.9%** | **PROMOTE_BROKERABLE_SIGNAGE_WITH_INSTALL_CAVEAT** — examples are genuine signage, usually with installation/removal |
| 67 | France — public-sector travel management agency | NOTICE_FIRST | **261 · 226 buyers · 30 repeat** | median **EUR 683,333** | **53 suppliers · top 14.3%** | **PROMOTE_AGENCY_INTERMEDIARY** — semantically clean travel-agency/travel-management demand |
| 68 | Québec — travel management agency | NOTICE_FIRST | **22 · 14 buyers · 4 repeat** | median **CAD 83,731.36** | **14 suppliers · top 14.3%** | **PROMOTE_AGENCY_INTERMEDIARY** |
| 69 | United Kingdom — travel management | NOTICE_FIRST | **20 · 17 buyers · 2 repeat** | median **GBP 8m** | **7 suppliers · top 25%** | **INVESTIGATE_AGENCY_MODEL** — real market, larger framework scale |
| 70 | United Kingdom — media planning / media buying agency | NOTICE_FIRST | **170 · 136 buyers · 26 repeat** | median **GBP 1,516,667** | **132 suppliers · top 8.4%** | **PROMOTE_AGENCY_INTERMEDIARY** — highly fragmented historical agency market |
| 71 | Ireland — media buying | NOTICE_FIRST | **16 · 15 buyers · 1 repeat** | median **EUR 425k** | **11 suppliers · top 11.1%** | **PROMOTE_AGENCY_INTERMEDIARY** |
| 72 | United Kingdom — ICT Value Added Reseller / Software VAR | NOTICE_FIRST | **17 · 14 buyers · 2 repeat** | median **GBP 135m** | **15 suppliers · top ~15.4%** | **PROMOTE_RESELLER_ECOSYSTEM_WITH_FRAMEWORK_RISK** — representative examples explicitly say VAR; historical winners include Softcat, XMA, CDW, Boxxe |
| 73 | United Kingdom — freight forwarding / logistics agency | NOTICE_FIRST | **10 · 10 buyers** | median **GBP 1m** | **12 linked suppliers · top ~18.2%** | **INVESTIGATE_LOGISTICS_INTERMEDIARY** — explicit freight-forwarding/logistics procurements |
| 74 | Canada — real-estate brokerage | NOTICE_FIRST | **21 · 9 buyers · 4 repeat** | median **CAD ~72k** | **7 suppliers · top ~14.3%** | **HOLD_LOCAL_REGULATED** — genuine brokerage market, but licensing/local presence are intrinsic |
| 75 | United Kingdom — real-estate brokerage | NOTICE_FIRST | **14 · 14 buyers** | median **GBP ~122k** | **17 linked suppliers · top ~15%** | **HOLD_LOCAL_REGULATED** |
| 76 | Ireland — insurance brokerage | NOTICE_FIRST | **32 · 17 buyers · 1 repeat** | median **EUR ~1.235m** | **7 suppliers · top ~50%** | **HOLD_REGULATED_CONCENTRATED** — genuine brokerage, but regulated and historically concentrated |

## Semantically rejected / narrowed broad census families

These do **not** count toward the 76 opportunity lanes.

### `ICT_HARDWARE_VAR — France`

**REJECT_FALSE_POSITIVE.** `Var` was the French département, not "Value Added Reseller". Representative titles are roads, electricity, heating and other public works. Similar short-token contamination must be assumed possible in other languages until exact examples are read.

### `PROCUREMENT_AGENT — France`

**REJECT_AS_BUSINESS_FAMILY.** Most titles describe normal supplies/services purchased **by** a `centrale d'achat` for its members. The supplier is not hired to act as a procurement agent.

### Broad `PACKAGING — France`

**HOLD_QA / NARROW_REQUIRED.** High-volume examples include waste collection, recycling and treatment of packaging. Actual packaging-material supply needs a stricter classifier.

### Broad `SIGNAGE — France / UK`

**HOLD_QA / NARROW_REQUIRED.** The broad text match captures construction/project scopes and unrelated works. Québec signage was promoted separately because its representative titles are substantially cleaner.

### Broad `IT_PERIPHERALS — UK`

**HOLD_QA / NARROW_REQUIRED.** Representative examples include huge technology frameworks and unrelated medical/equipment scopes. A title-led peripherals classifier is required before promotion.

## What Atlas v3 changes strategically

### 1. Standardized distribution is now one of the largest historical opportunity families

The archive shows that procurement of mundane catalogue goods is not a side note. Office stationery alone produces over a thousand historical France notices with an extremely fragmented supplier field. Standard furniture and workwear show the same pattern. These businesses may have lower gross margins than digital services, but the underlying fulfilment model can be very simple: distributor quote → markup → public buyer.

### 2. Agency/intermediary businesses are broader than software resale

Travel management and media buying are explicit public-sector agency markets with broad buyer bases. Freight forwarding is smaller but structurally similar. This validates a broader thesis: public buyers repeatedly outsource **intermediation itself**.

### 3. Semantic QA materially changes conclusions

Without title QA, `Var` would have fabricated a giant French ICT-reseller market and `centrale d'achat` would have fabricated a procurement-agent market. Historical market structure is useful only after the cohort meaning itself is validated.

### 4. The strongest families now span four execution archetypes

- **Digital / AI-leveraged services:** web, design, translation, transcription, data/IT support.
- **Human-capital brokerage:** Australia ICT talent/general staffing, France/Canada/Germany temp staffing, USA support teams.
- **Standard-goods distribution:** cleaning/hygiene, office supplies, furniture, workwear/PPE, paper/envelopes.
- **Explicit agency/intermediary:** software reseller/VAR, travel management, media buying, print/mail fulfilment, freight forwarding.

## Next archive-only work

1. Split France office supplies into paper, stationery, toner/ink, office consumables, school supplies and online catalogue frameworks.
2. Split France workwear/PPE into outright product supply vs rental/laundry/managed service.
3. Tighten product classifiers for packaging, signage and IT peripherals rather than discarding the underlying markets.
4. Split Australia ICT talent into developer, business analyst, data, cyber, technical writer and PM roles and map repeat buyers/winners.
5. Split USA admin/BPO into low-specialization operational work vs clearance/professional-heavy work.
6. Keep expanding until **75–100+ semantically QA'd historical lanes**, but only when each new lane has evidence-backed meaning, buyer structure and economics.
