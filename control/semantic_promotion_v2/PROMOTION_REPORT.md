# SPM Semantic Promotion QA v2

Version: `SPM_SEMANTIC_PROMOTION_V2_1_MANUAL_QA`

This gate re-tests expansion lanes discovered by the exhaustive reader with stricter semantics. It does not replace Market Intelligence v9 for already-QA-clean lanes and does not satisfy any live DCE requirement.

- Loose expansion candidates: **41,301**
- Strict semantic candidates: **5,788**
- Strict candidates on OPEN_PUBLIC routes: **3,081**

## Promotion decisions

|Lane|Decision|Strict hits|Open-public|Strict/loose|Rationale|
|---|---|---:|---:|---:|---|
|Software licences / SaaS resale|PROMOTE_BROKER|438|92|13.50%|Low-delivery software resale/subscription motion; validate reseller/channel constraints per DCE.|
|Hardware / AV resale|HOLD_BROKER|0|0|0.00%|Potential broker margin but working-capital, warranty, delivery and installation burden can dominate.|
|Office supplies / consumables resale|HOLD_BROKER|1,983|1,512|68.64%|Easy fulfilment but likely commodity margins/logistics; require margin and payment-term proof.|
|Uniforms / PPE resale|HOLD_BROKER|0|0|0.00%|Brokerable but sizing, standards, samples and inventory may create execution pain.|
|Training / e-learning|PROMOTE_CORE|1,544|680|79.83%|Only strict digital-learning/LMS/content subset; classroom/trainer-heavy work is excluded.|
|Promotional merchandise|PROMOTE_BROKER|142|97|74.74%|Brokerable physical production lane; DCE must allow subcontracting and acceptable samples/logistics.|
|Signage / display production|HOLD_BROKER|0|0|0.00%|Pure production can be brokered, but installation/site burden is common and explicitly filtered.|
|Courier / mail fulfilment|REJECT_CORE|137|64|14.94%|Operational physical network business; useful only as buyer/subcontractor intelligence.|
|Event support / production|HOLD|14|7|3.62%|Even clean titles frequently conceal onsite/cadence burden; no live bonus until DCE/sample validation.|
|Recruitment / temporary staffing|REJECT_CORE|1,328|546|24.33%|Labour/employer/compliance motion is outside lean SPM core.|

## Interpretation

- `PROMOTE_CORE` may contribute a small pre-DCE live discovery bonus after manual sample review.
- `PROMOTE_BROKER` is a separate resale/arbitrage motion; it must not be treated as AI-native fulfilment.
- `HOLD*` remains searchable but contributes no historical priority bonus until further QA/economics validation.
- `REJECT_CORE` may still be commercially useful to a different operator model, but is outside SPM lean-core scoring.
- All mandatory eligibility, references, turnover, insurance, language, onsite and subcontracting rules remain DCE-controlled.