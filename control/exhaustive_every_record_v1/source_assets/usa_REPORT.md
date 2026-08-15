# Exhaustive every-record read — USASPENDING_V1

Version: `SPM_EXHAUSTIVE_RECORD_READER_V1`
Grain: `AWARD_FIRST_PROCUREMENT`

- Procurement rows processed: **15,842,317**
- Award rows scanned: **15,842,317**
- Award↔supplier links scanned: **15,842,312**
- Distinct procurement IDs: **15,842,317**
- Integrity: **PASS** — scan ordinal 1..15,842,317; no pre-scoring row filter.

## Discovery accounting

- RESIDUAL: 13,242,293
- OPEN_WORLD_CANDIDATE: 1,430,750
- KNOWN_LANE: 1,169,274

## Broad families

|Family|Records|Buyers|Median value|Median bidders|Avg priority|Open-world|
|---|---:|---:|---:|---:|---:|---:|
|Other / unknown|8,998,251|2,370|499.94|3.0|38.52|0|
|Healthcare / medical|1,681,755|1,280|402.74|1.0|38.63|0|
|Office / administrative goods|1,114,561|1,660|160.0|1.0|50.7|162,766|
|Facilities / cleaning / maintenance|775,221|2,071|235.28|2.0|35.74|0|
|Laboratory / scientific|773,665|1,424|380.77|28.0|38.21|0|
|Other goods / resale|457,035|1,814|1443.5349999999999|3.0|39.68|455,241|
|Transport / logistics|341,449|2,013|15891.51|10.0|39.68|0|
|Creative / communications / print|319,761|2,062|508.54499999999996|3.0|53.69|226,936|
|Hardware / AV / electronics|278,841|1,620|449.68|2.0|39.54|258,706|
|IT / software / cyber|230,076|2,094|40757.425|2.0|58.09|208,971|
|Construction / works|197,398|1,612|2872.5649999999996|3.0|37.69|0|
|Other services|107,425|2,021|39188.854999999996|1.0|50.63|0|
|Food / catering|83,988|461|800.13|1.0|39.66|0|
|Architecture / engineering|71,980|1,535|298609.33|2.0|50.34|0|
|Training / education|58,553|1,745|23589.86|1.0|54.26|56,906|
|Energy / utilities|56,485|752|193.31|8.0|39.09|0|
|Property / real estate|56,392|1,200|230.65|15.0|40.4|0|
|Consulting / research / audit|55,042|1,382|249175.0|2.0|60.14|52,598|
|Environment / waste|48,847|1,087|8378.0|2.0|43.23|0|
|Staffing / HR|43,425|1,372|18231.735|3.0|50.37|0|

## Named lanes by route/currency

|Lane|Route|Currency|Records|Buyers|Median|P25|P75|Median bidders|Avg priority|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
|Office supplies / consumables resale|AWARD_FIRST_EVIDENCE|USD|1,034,065|1,105|135.0|46.75|430.42|1.0|53.8|
|Hardware / AV resale|AWARD_FIRST_EVIDENCE|USD|33,578|1,514|4907.07|613.2|58970.024999999994|2.0|61.57|
|Call centre / helpdesk operations|AWARD_FIRST_EVIDENCE|USD|31,858|1,129|28294.6|4814.46|116445.0|2.0|61.16|
|Translation|AWARD_FIRST_EVIDENCE|USD|23,131|631|2508.0|390.0|14258.48|1.0|74.52|
|Data entry / clerical processing|AWARD_FIRST_EVIDENCE|USD|12,801|131|146.4|81.12|304.2|2.0|65.91|
|Transcription / captioning|AWARD_FIRST_EVIDENCE|USD|8,541|310|181.44|72.68|868.69|2.0|59.84|
|Software licences / SaaS resale|AWARD_FIRST_EVIDENCE|USD|8,100|722|88180.66|27825.145|350611.6075|1.0|78.49|
|Uniforms / PPE resale|AWARD_FIRST_EVIDENCE|USD|4,887|562|11858.5|129.5|64707.740000000005|1.0|59.61|
|Courier / mail fulfilment|AWARD_FIRST_EVIDENCE|USD|3,206|517|14155.634999999998|1500.0|112464.0675|1.0|56.4|
|Recruitment / temporary staffing|AWARD_FIRST_EVIDENCE|USD|1,809|236|147.98|19.04|121698.31999999999|3.0|56.63|
|Survey / market research|AWARD_FIRST_EVIDENCE|USD|1,725|304|68376.5|12666.5|315493.28|2.0|72.55|
|Training / e-learning|AWARD_FIRST_EVIDENCE|USD|1,161|360|259310.07|62078.0|1471680.0|1.0|76.37|
|Website support / accessibility / hosting|AWARD_FIRST_EVIDENCE|USD|828|221|356673.65|86369.5|1733894.065|1.0|80.55|
|Signage / display production|AWARD_FIRST_EVIDENCE|USD|814|293|38367.835|12225.2975|175575.125|2.0|71.25|
|Document digitization / OCR / scanning|AWARD_FIRST_EVIDENCE|USD|416|176|129436.905|26982.6|834315.265|1.0|78.34|
|Video production / post-production|AWARD_FIRST_EVIDENCE|USD|355|138|88674.06|16452.095|1477101.395|1.0|72.07|
|Cloud / hosting / managed IT|AWARD_FIRST_EVIDENCE|USD|303|106|521756.76|79242.72|3257321.84|1.0|67.67|
|Social media / community management|AWARD_FIRST_EVIDENCE|USD|296|164|138321.375|30340.875|416468.355|1.5|79.13|
|Website / CMS build or redesign|AWARD_FIRST_EVIDENCE|USD|293|147|91635.0|17182.31|359810.94|1.0|80.33|
|Printing / mailing / routing|AWARD_FIRST_EVIDENCE|USD|265|105|3113.7|0.0|30000.0|1.0|69.49|
|Graphic design / layout / DTP|AWARD_FIRST_EVIDENCE|USD|216|115|57811.65|14615.66|248275.81000000003|1.0|75.72|
|Promotional merchandise|AWARD_FIRST_EVIDENCE|USD|208|64|39944.0|8728.150000000001|127385.15|2.0|72.26|
|Event support / production|AWARD_FIRST_EVIDENCE|USD|200|96|74586.745|23836.5925|315463.7525|2.0|65.8|
|Media / press monitoring|AWARD_FIRST_EVIDENCE|USD|170|106|50587.9|19879.9025|128068.4375|2.0|77.11|
|SEO / digital marketing|AWARD_FIRST_EVIDENCE|USD|39|29|130085.52|26378.93|549378.49|2.0|77.56|

## What 'every record' means here

Every procurement row was materialized and scored before aggregation. Every award row and award-supplier link row was scanned. This is exhaustive structured-data processing, not a claim that every underlying DCE/PDF attachment was manually read; DCE deep-read is a separate downstream gate for live/final bidding.
