from __future__ import annotations

import dce_country_benchmark as base
import dce_country_benchmark_v2 as quality


# Wealthy / high-priority jurisdictions split by actual DCE portal family.
# Labels are deliberately portal-specific: a country-level average hides cases
# such as Scotland (good) versus UK eSenders, or BOAMP (notice router) versus
# PLACE/Achatpublic/AWS (document hosts).
TARGET_FAMILIES = [
    "UK-SCOTLAND", "UK-ATAMIS", "UK-PROCONTRACT", "UK-DELTA", "UK-INTEND", "UK-JAGGAER", "UK-NOTICE-ROUTER",
    "FR-BOAMP", "FR-PLACE", "FR-ACHATPUBLIC", "FR-AWS", "FR-MAXIMILIEN", "FR-MARCHES-SECUR", "FR-E-MARCHESPUBLICS",
    "US-SAM", "CA-CANADABUYS", "CA-QC-SEAO", "AU-AUSTENDER",
    "BE-EPROC", "NL-TENDERNED",
    "DE-DOE", "DE-EVERGABE-NRW", "DE-EVERGABE-DE",
    "CH-SIMAP", "IE-ETENDERS", "LU-PMP",
    "SE-EAVROP", "SE-CLIRA", "SE-TENDSIGN", "SE-KOMMERSANNONS",
    "NO-DOFFIN", "NO-ARTIFIK", "DK-UDBUD", "FI-HILMA",
    "NZ-GETS", "NZ-TENDERLINK",
]

PORTAL_FAMILY = {
    "SCOTLAND_PCS": "UK-SCOTLAND", "UK_PCS_OCDS": "UK-SCOTLAND", "PUBLIC_CONTRACTS_SCOTLAND": "UK-SCOTLAND",
    "UK_ATAMIS": "UK-ATAMIS",
    "UK_PROCONTRACT": "UK-PROCONTRACT", "UK_DUENORTH": "UK-PROCONTRACT",
    "UK_DELTA": "UK-DELTA", "UK_DELTA_ESOURCING": "UK-DELTA",
    "UK_INTEND": "UK-INTEND", "UK_IN_TEND": "UK-INTEND",
    "UK_JAGGAER": "UK-JAGGAER", "UK_BRAVOSOLUTION": "UK-JAGGAER",
    "UK_FIND_A_TENDER": "UK-NOTICE-ROUTER", "UK_FTS_OCDS": "UK-NOTICE-ROUTER", "UK_CONTRACTS_FINDER": "UK-NOTICE-ROUTER",
    "FR_BOAMP": "FR-BOAMP", "FR_PLACE": "FR-PLACE", "FR_ACHATPUBLIC": "FR-ACHATPUBLIC", "FR_AWS": "FR-AWS",
    "FR_MAXIMILIEN": "FR-MAXIMILIEN", "FR_MARCHES_SECUR": "FR-MARCHES-SECUR", "FR_E_MARCHESPUBLICS": "FR-E-MARCHESPUBLICS",
    "US_SAM": "US-SAM", "US_SAM_BULK": "US-SAM", "SAM_GOV": "US-SAM", "SAM": "US-SAM",
    "CA_CANADABUYS": "CA-CANADABUYS", "CANADABUYS": "CA-CANADABUYS",
    "QC_SEAO": "CA-QC-SEAO", "CA_SEAO": "CA-QC-SEAO", "SEAO": "CA-QC-SEAO",
    "AU_AUSTENDER": "AU-AUSTENDER", "AUSTENDER": "AU-AUSTENDER",
    "BE_EPROC": "BE-EPROC", "BE_EPROC_V11": "BE-EPROC",
    "NL_TENDERNED": "NL-TENDERNED", "NL_TENDERNED_RSS": "NL-TENDERNED", "NL_TENDERNED_PUBLIC": "NL-TENDERNED",
    "DE_DOE": "DE-DOE", "DE_EVERGABE_NRW": "DE-EVERGABE-NRW", "DE_EVERGABE_DE": "DE-EVERGABE-DE",
    "CH_SIMAP": "CH-SIMAP", "CH_SIMAP_PUBLIC": "CH-SIMAP",
    "IRELAND_ETENDERS": "IE-ETENDERS", "IE_ETENDERS": "IE-ETENDERS", "ETENDERS_IRELAND": "IE-ETENDERS",
    "LUX_PMP": "LU-PMP", "LU_PMP": "LU-PMP", "LUXEMBOURG_PMP": "LU-PMP",
    "SE_EAVROP": "SE-EAVROP", "SE_CLIRA": "SE-CLIRA", "SE_TENDSIGN": "SE-TENDSIGN", "SE_KOMMERSANNONS": "SE-KOMMERSANNONS",
    "NO_DOFFIN": "NO-DOFFIN", "NO_ARTIFIK": "NO-ARTIFIK",
    "DK_UDBUD": "DK-UDBUD", "DK_UDBUD_DK": "DK-UDBUD", "DK_UDBUD_PUBLIC": "DK-UDBUD",
    "FI_HILMA": "FI-HILMA",
    "NZ_GETS": "NZ-GETS", "NZ_TENDERLINK": "NZ-TENDERLINK",
}

PREFIX_FAMILY = [
    ("UK_PCS_OCDS:", "UK-SCOTLAND"), ("uk_pcs_ocds:", "UK-SCOTLAND"),
    ("QC-", "CA-QC-SEAO"), ("US-", "US-SAM"), ("CA-", "CA-CANADABUYS"),
    ("BE-", "BE-EPROC"), ("NL-", "NL-TENDERNED"), ("CH-", "CH-SIMAP"),
    ("IE-", "IE-ETENDERS"), ("LU-", "LU-PMP"), ("DK-", "DK-UDBUD"), ("FI-", "FI-HILMA"),
]


def infer_family(rec: dict) -> str:
    for raw in (
        rec.get("portal"), rec.get("portal_key"), rec.get("source"),
        rec.get("selection_portal"), rec.get("source_portal"),
    ):
        portal = str(raw or "").strip().upper()
        if portal in PORTAL_FAMILY:
            return PORTAL_FAMILY[portal]
    cid = str(rec.get("candidate_id") or "")
    for prefix, family in PREFIX_FAMILY:
        if cid.startswith(prefix):
            return family
    return ""


# Reuse the V2 production-quality scoring stack while changing only the sampling
# dimension from country to portal family.
base.TARGET_COUNTRIES[:] = TARGET_FAMILIES
base.infer_country = infer_family
base.cmd_summarize_country = quality.cmd_summarize_country
base.cmd_aggregate = quality.cmd_aggregate


if __name__ == "__main__":
    base.main()
