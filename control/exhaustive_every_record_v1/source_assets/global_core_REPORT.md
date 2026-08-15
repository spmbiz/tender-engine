# Exhaustive every-record read — GLOBAL_CORE_V4

Version: `SPM_EXHAUSTIVE_RECORD_READER_V1`
Grain: `NOTICE_FIRST_TENDER`

- Procurement rows processed: **2,250,547**
- Award rows scanned: **4,286,784**
- Award↔supplier links scanned: **3,937,663**
- Distinct procurement IDs: **2,250,547**
- Integrity: **PASS** — scan ordinal 1..2,250,547; no pre-scoring row filter.

## Discovery accounting

- RESIDUAL: 1,931,571
- OPEN_WORLD_CANDIDATE: 248,730
- KNOWN_LANE: 70,246

## Broad families

|Family|Records|Buyers|Median value|Median bidders|Avg priority|Open-world|
|---|---:|---:|---:|---:|---:|---:|
|Other / unknown|1,580,478|117,496|433650.0|2.0|47.88|0|
|Other services|108,235|24,220|131848.215|1.0|50.76|0|
|Construction / works|62,369|18,527|500000.0|3.0|41.92|0|
|Transport / logistics|61,667|16,393|320281.6625|3.0|43.61|0|
|Other goods / resale|60,977|16,026|212087.435|1.0|44.61|58,283|
|Training / education|57,931|10,714|240000.0|2.0|56.82|45,612|
|IT / software / cyber|54,136|14,609|393968.5|1.0|58.34|47,127|
|Creative / communications / print|45,583|14,797|400000.0|2.0|57.67|38,662|
|Consulting / research / audit|35,022|11,068|136476.16|1.0|56.79|33,405|
|Facilities / cleaning / maintenance|34,287|11,856|354551.25|2.0|43.01|0|
|Healthcare / medical|31,126|5,559|383977.5|1.0|50.25|0|
|Hardware / AV / electronics|23,152|7,404|425002.7|2.0|54.15|11,691|
|Architecture / engineering|19,350|6,666|110243.435|1.0|49.42|0|
|Web / digital|14,833|4,367|350000.0|3.0|64.88|9,487|
|Events / exhibitions|11,215|4,761|400000.0|2.0|49.38|0|
|Laboratory / scientific|9,601|3,725|205854.75|1.0|49.68|0|
|Staffing / HR|8,728|4,420|289207.93|2.0|54.61|0|
|Food / catering|7,877|5,166|450905.18|3.0|48.29|0|
|Security / safety|7,835|3,881|150000.0|1.0|48.62|0|
|Environment / waste|3,730|1,688|500000.0|3.0|48.1|0|

## Named lanes by route/currency

|Lane|Route|Currency|Records|Buyers|Median|P25|P75|Median bidders|Avg priority|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
|Translation|OPEN_PUBLIC|EUR|12,859|227|366946.0|154000.0|836000.0|6.0|69.66|
|Hardware / AV resale|UNKNOWN|UNKNOWN|3,693|1,771|430842.52|126686.84|1548447.0|2.0|62.34|
|Hardware / AV resale|OPEN_PUBLIC|EUR|3,204|808|223500.0|50000.0|700000.0|3.0|64.36|
|Hardware / AV resale|UNKNOWN|EUR|3,073|1,452|482352.88|215310.905|1373245.06|2.0|65.87|
|Signage / display production|OPEN_PUBLIC|EUR|2,175|1,463|362512.0|150000.0|898000.0|3.0|62.71|
|Printing / mailing / routing|OPEN_PUBLIC|EUR|1,968|1,457|400000.0|167500.0|800000.0|4.5|70.35|
|Recruitment / temporary staffing|OPEN_PUBLIC|EUR|1,802|694|328930.96|94013.76000000001|1250000.0|5.0|59.84|
|Hardware / AV resale|OPEN_PUBLIC|GBP|1,525|789|450000.0|131529.72999999998|2270833.0|5.0|72.87|
|Office supplies / consumables resale|OPEN_PUBLIC|EUR|1,419|949|300250.0|125000.0|800000.0|4.0|63.05|
|Hardware / AV resale|DIRECT_NONCOMPETITIVE|GBP|1,406|496|80000.0|35759.75|229630.0|1.0|70.19|
|Uniforms / PPE resale|OPEN_PUBLIC|EUR|1,109|864|260000.0|111157.285|644000.0|3.0|61.0|
|Website support / accessibility / hosting|OPEN_PUBLIC|CAD|1,008|109|210000.0|87433.3|613878.22|4.0|68.77|
|Hardware / AV resale|UNKNOWN|GBP|936|498|600000.0|70885.0|5000000.0|1.0|66.81|
|Website / CMS build or redesign|OPEN_PUBLIC|CAD|804|100|157627.05|62010.0|418085.48|6.0|71.03|
|Website / CMS build or redesign|OPEN_PUBLIC|EUR|764|335|320000.0|93108.0|1042635.5|4.0|72.62|
|Website support / accessibility / hosting|OPEN_PUBLIC|EUR|763|445|385847.5|135105.75|746311.0|5.0|72.14|
|Survey / market research|OPEN_PUBLIC|EUR|708|501|217090.0|90000.0|540000.0|3.0|66.26|
|Hardware / AV resale|UNKNOWN|PLN|679|267|332898.94|81981.3675|1566864.5|2.0|67.18|
|Recruitment / temporary staffing|COMPETITIVE_OTHER|EUR|654|268|188193.195|1.0|697566.6025|3.0|58.02|
|Uniforms / PPE resale|UNKNOWN|EUR|593|342|353400.0|112962.5|1002086.5|2.0|66.42|
|Hardware / AV resale|OPEN_PUBLIC|CAD|589|137|217107.82|71848.25|894944.575|2.0|67.36|
|Recruitment / temporary staffing|DIRECT_NONCOMPETITIVE|GBP|572|274|130967.77249999999|50000.0|440490.0|1.0|64.09|
|Uniforms / PPE resale|UNKNOWN|UNKNOWN|569|375|413605.0|115462.76|1662175.0|2.0|60.86|
|Recruitment / temporary staffing|UNKNOWN|EUR|567|103|700000.0|175360.0|4450000.0|2.0|55.23|
|Software licences / SaaS resale|OPEN_PUBLIC|EUR|540|312|255243.12|80000.0|869900.0|2.0|71.56|

## What 'every record' means here

Every procurement row was materialized and scored before aggregation. Every award row and award-supplier link row was scanned. This is exhaustive structured-data processing, not a claim that every underlying DCE/PDF attachment was manually read; DCE deep-read is a separate downstream gate for live/final bidding.
