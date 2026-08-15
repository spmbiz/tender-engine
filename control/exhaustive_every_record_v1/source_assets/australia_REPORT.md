# Exhaustive every-record read — AUSTENDER_V1

Version: `SPM_EXHAUSTIVE_RECORD_READER_V1`
Grain: `AWARD_FIRST_PROCUREMENT`

- Procurement rows processed: **178,211**
- Award rows scanned: **178,211**
- Award↔supplier links scanned: **178,211**
- Distinct procurement IDs: **178,211**
- Integrity: **PASS** — scan ordinal 1..178,211; no pre-scoring row filter.

## Discovery accounting

- RESIDUAL: 125,036
- OPEN_WORLD_CANDIDATE: 43,194
- KNOWN_LANE: 9,981

## Broad families

|Family|Records|Buyers|Median value|Median bidders|Avg priority|Open-world|
|---|---:|---:|---:|---:|---:|---:|
|Other / unknown|61,959|132|58395.0|NA|47.08|0|
|Other services|28,081|134|100000.0|NA|50.6|0|
|Transport / logistics|11,989|92|50000.0|NA|42.2|0|
|IT / software / cyber|10,962|123|107390.08499999999|NA|61.35|7,934|
|Training / education|9,938|119|25162.5|NA|52.66|9,742|
|Other goods / resale|8,691|90|32459.86|NA|43.61|8,439|
|Creative / communications / print|6,769|125|60000.0|NA|56.12|5,927|
|Facilities / cleaning / maintenance|6,708|97|31086.515|NA|41.18|0|
|Consulting / research / audit|5,784|124|116009.6|NA|61.58|4,281|
|Hardware / AV / electronics|5,474|87|51664.25|NA|46.82|4,904|
|Staffing / HR|5,203|100|134085.37|NA|52.97|0|
|Laboratory / scientific|2,282|64|36230.369999999995|NA|46.03|0|
|Events / exhibitions|2,038|94|26072.25|NA|46.75|0|
|Construction / works|2,018|68|79982.35|NA|42.45|0|
|Office / administrative goods|1,882|79|25118.04|NA|44.6|1,670|
|Architecture / engineering|1,841|76|302871.8|NA|49.3|0|
|Property / real estate|1,804|95|365599.0|NA|49.55|0|
|Healthcare / medical|1,573|42|60500.0|NA|46.99|0|
|Food / catering|957|44|17694.6|NA|43.8|0|
|Security / safety|624|55|109687.875|NA|48.07|0|

## Named lanes by route/currency

|Lane|Route|Currency|Records|Buyers|Median|P25|P75|Median bidders|Avg priority|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
|Software licences / SaaS resale|AWARD_FIRST_EVIDENCE|AUD|2,838|89|80395.94|32050.302499999998|274162.27|NA|74.49|
|Hardware / AV resale|AWARD_FIRST_EVIDENCE|AUD|2,478|103|83155.25|25567.575|330000.0|NA|69.25|
|Recruitment / temporary staffing|AWARD_FIRST_EVIDENCE|AUD|1,458|78|27500.0|16011.24|78300.0|NA|57.92|
|Uniforms / PPE resale|AWARD_FIRST_EVIDENCE|AUD|578|19|49692.735|21991.75|170179.7625|NA|62.36|
|Event support / production|AWARD_FIRST_EVIDENCE|AUD|280|38|32754.545|17621.989999999998|80793.61249999999|NA|57.98|
|Printing / mailing / routing|AWARD_FIRST_EVIDENCE|AUD|256|44|22009.0|13658.149999999998|44066.0|NA|70.65|
|Survey / market research|AWARD_FIRST_EVIDENCE|AUD|225|49|109998.9|39905.0|250000.0|NA|73.06|
|Office supplies / consumables resale|AWARD_FIRST_EVIDENCE|AUD|216|70|29294.02|16176.375|109917.5|NA|61.33|
|Training / e-learning|AWARD_FIRST_EVIDENCE|AUD|209|67|29700.0|14410.0|129790.1|NA|69.41|
|Website / CMS build or redesign|AWARD_FIRST_EVIDENCE|AUD|195|63|92928.0|36474.240000000005|244100.0|NA|79.04|
|Graphic design / layout / DTP|AWARD_FIRST_EVIDENCE|AUD|189|49|30000.0|16500.0|70000.0|NA|72.1|
|Translation|AWARD_FIRST_EVIDENCE|AUD|170|45|26150.3|14151.94|69068.01|NA|74.69|
|Courier / mail fulfilment|AWARD_FIRST_EVIDENCE|AUD|130|39|36329.905|18386.4325|107500.0|NA|57.04|
|Website support / accessibility / hosting|AWARD_FIRST_EVIDENCE|AUD|110|60|70676.2|38678.75|227378.25|NA|77.58|
|Promotional merchandise|AWARD_FIRST_EVIDENCE|AUD|100|9|17848.8|12000.5775|31082.0|NA|69.12|
|Media / press monitoring|AWARD_FIRST_EVIDENCE|AUD|94|56|94974.0|40095.0|273146.25|NA|73.86|
|Signage / display production|AWARD_FIRST_EVIDENCE|AUD|83|25|22075.38|12904.815|55204.315|NA|68.53|
|Social media / community management|AWARD_FIRST_EVIDENCE|AUD|79|44|59400.0|23883.75|227791.74|NA|74.77|
|Transcription / captioning|AWARD_FIRST_EVIDENCE|AUD|78|22|55000.0|24065.0|150000.0|NA|77.39|
|Document digitization / OCR / scanning|AWARD_FIRST_EVIDENCE|AUD|58|18|141484.19|53196.0025|998509.105|NA|77.19|
|Call centre / helpdesk operations|AWARD_FIRST_EVIDENCE|AUD|53|26|160000.0|85800.0|360000.0|NA|63.49|
|Video production / post-production|AWARD_FIRST_EVIDENCE|AUD|50|23|49747.46|27190.35|130625.0|NA|71.57|
|Cloud / hosting / managed IT|AWARD_FIRST_EVIDENCE|AUD|28|18|149096.35|25669.0|556856.3400000001|NA|60.53|
|Report / publication production|AWARD_FIRST_EVIDENCE|AUD|16|11|20846.65|14898.2875|30586.625|NA|67.48|
|SEO / digital marketing|AWARD_FIRST_EVIDENCE|AUD|8|6|18725.059999999998|15754.75|33299.2975|NA|71.82|

## What 'every record' means here

Every procurement row was materialized and scored before aggregation. Every award row and award-supplier link row was scanned. This is exhaustive structured-data processing, not a claim that every underlying DCE/PDF attachment was manually read; DCE deep-read is a separate downstream gate for live/final bidding.
