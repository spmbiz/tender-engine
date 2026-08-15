from __future__ import annotations

from pathlib import Path


def qi(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def lit(x: str) -> str:
    return "'" + x.replace("'", "''") + "'"


def choose(cols: set[str], *names: str) -> str | None:
    """Case-insensitive schema resolver with context-safe canonical aliases.

    The three canonical warehouses intentionally retain native-ish field names.
    Add aliases only for the semantic family requested by the caller so, for
    example, a missing Buyer_ID can never silently fall back to a tender ID.
    """
    m = {c.casefold(): c for c in cols}
    candidates = list(names)
    folded = {n.casefold() for n in names}

    # Procurement/tender identity. This branch intentionally keys off Tender_ID
    # rather than generic Contract_ID because award IDs use a different family.
    if 'tender_id' in folded or 'procurement_id' in folded:
        candidates += [
            'Historical_Tender_ID', 'Procurement_Key', 'Source_Contract_ID',
            'Official_Notice_ID', 'Procurement_Reference', 'US_Contract_Award_Unique_Key',
        ]
    # Award identity.
    if 'award_id' in folded:
        candidates += ['Linked_Award_ID', 'US_Contract_Award_Unique_Key', 'Source_Contract_ID']
    # Buyer identity/name.
    if 'buyer_id' in folded or 'agency_id' in folded:
        candidates += ['Source_Buyer_ID']
    if 'buyer_name' in folded or 'contracting_authority' in folded or 'awarding_agency' in folded:
        candidates += ['Agency_Name']
    # Warehouse/source provenance.
    if 'source' in folded or 'warehouse_source' in folded:
        candidates += ['Source_System', 'Source_Platform']
    # Value/date/code/procedure aliases used by canonical normalized releases.
    if 'estimated_value' in folded or 'contract_value' in folded or 'award_value' in folded or 'total_obligation' in folded:
        candidates += ['Official_Estimated_Value', 'Estimated_Value_Field', 'Estimate_Field']
    if 'publication_date' in folded:
        candidates += ['Latest_Publication_Date']
    if 'cpv' in folded or 'cpv_code' in folded or 'naics' in folded or 'naics_code' in folded or 'psc' in folded or 'psc_code' in folded or 'category_code' in folded:
        candidates += ['Main_CPV', 'CPV_NAICS_or_Local_Code', 'NAICS_Code', 'PSC_Code']
    if 'cpv_description' in folded or 'naics_description' in folded or 'psc_description' in folded or 'code_description' in folded:
        candidates += ['Raw_CPV_Description', 'Raw_Spend_Category', 'Subcategory', 'Category']
    if 'procurement_procedure' in folded or 'procedure' in folded or 'procedure_type' in folded:
        candidates += ['Competition_Type', 'Extent_Competed']
    if 'scope_summary' in folded or 'scope' in folded or 'description' in folded:
        candidates += ['Description']
    if 'url' in folded:
        candidates += ['Primary_Source_URL', 'Source_URL']
    # Award evidence aliases.
    if 'bidder_count' in folded or 'tenderer_count' in folded or 'number_of_bids' in folded:
        candidates += ['Official_Bidder_Count']
    if 'award_date' in folded or 'action_date' in folded or 'contract_start_date' in folded:
        candidates += ['Publication_Date']
    if 'supplier_id' in folded or 'recipient_id' in folded:
        candidates += ['Winner_ID', 'Recipient_UEI', 'Recipient_DUNS']
    if 'supplier_name' in folded or 'recipient_name' in folded:
        candidates += ['Winner_Name', 'Recipient_Name']

    seen = set()
    for n in candidates:
        k = n.casefold()
        if k in seen:
            continue
        seen.add(k)
        if k in m:
            return m[k]
    return None


def relation(path: Path) -> str:
    p = lit(str(path))
    if path.suffix.lower() == '.parquet':
        return f"read_parquet({p})"
    return f"read_csv_auto({p}, header=true, all_varchar=true, sample_size=200000, ignore_errors=false, compression='auto')"


def cols_for(con, rel: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()}


def text_expr(c: str | None, default="''") -> str:
    return f"trim(cast({qi(c)} as varchar))" if c else default


def double_expr(c: str | None) -> str:
    return f"try_cast({qi(c)} as double)" if c else "NULL::DOUBLE"


def date_expr(c: str | None) -> str:
    return f"try_cast({qi(c)} as date)" if c else "NULL::DATE"


def route_case(source: str, proc: str, grain: str) -> str:
    if grain == 'AWARD_FIRST_PROCUREMENT':
        return "'AWARD_FIRST_EVIDENCE'"
    sl = f"lower(coalesce({source},''))"
    pl = f"lower(coalesce({proc},''))"
    return f"""
    CASE
      WHEN {sl}='quebec' THEN CASE
        WHEN {pl} LIKE '%gré à gré%' THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%invitation%' THEN 'LIMITED_INVITATION'
        WHEN ({pl} LIKE '%avis d’appel d’offres%' OR {pl} LIKE '%avis d''appel d''offres%') THEN 'OPEN_PUBLIC'
        ELSE 'UNKNOWN' END
      WHEN {sl}='canada federal' THEN CASE
        WHEN {pl}='competitive - open bidding' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('competitive - traditional','competitive - selective tendering','competitive - limited tendering') THEN 'COMPETITIVE_OTHER'
        WHEN {pl}='advance contract award notice' OR {pl}='non-competitive' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='france' THEN CASE
        WHEN {pl} LIKE 'ouvert/%' OR {pl}='ouvert/' THEN 'OPEN_PUBLIC'
        WHEN {pl} LIKE 'procedure_adapte/%' OR {pl}='procedure_adapte/' OR {pl} LIKE 'restreint/%' OR {pl}='restreint/' OR {pl} LIKE '%avec_pub_prealable%' OR {pl} LIKE 'dialogue_competitif/%' THEN 'COMPETITIVE_OTHER'
        WHEN {pl} LIKE '%sans_pub%' OR {pl} LIKE 'attribue_sans_pub%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='germany' THEN CASE
        WHEN {pl} IN ('de-open','open','us-open') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted','de-restricted-w-call','neg-w-call','de-comp-w-call','de-comp-neg-w-call','comp-tend','comp-dial','us-neg-w-call','us-res-tw') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('neg-wo-call','de-restricted-wo-call','de-comp-wo-call','de-comp-neg-wo-call','oth-single','us-neg-wo-call','us-free-no-tw','us-res-no-tw') OR {pl} LIKE '%freihändige%' OR {pl} LIKE '%freihandige%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='ireland' THEN CASE
        WHEN {pl}='open procedure' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','competitive procedure with negotiation','simplified','competitive dialogue') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} LIKE '%direct%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {pl} LIKE '%open%' OR {pl} LIKE '%ouvert%' THEN 'OPEN_PUBLIC'
      WHEN {pl} LIKE '%direct%' OR {pl} LIKE '%single%' OR {pl} LIKE '%non-competitive%' THEN 'DIRECT_NONCOMPETITIVE'
      WHEN {pl} LIKE '%restricted%' OR {pl} LIKE '%negotiat%' OR {pl} LIKE '%competitive%' THEN 'COMPETITIVE_OTHER'
      ELSE 'UNKNOWN'
    END
    """
