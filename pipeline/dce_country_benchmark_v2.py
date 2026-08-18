from __future__ import annotations

import dce_country_benchmark as base


EXTRA_TARGETS = ["CA-QC", "DK", "FI", "SI", "ZA", "AU"]
base.TARGET_COUNTRIES[:] = [
    "LU", "IE", "GB-SCT", "GB", "GR", "CA", "CA-QC", "US", "ZA",
    "SK", "HU", "PL", "ES", "DE", "BG", "BE", "NL", "EE", "CH",
    "FR", "LV", "CZ", "DK", "FI", "SI", "RO", "HR", "AT", "IT",
    "PT", "SE", "NO", "NZ", "AU",
]

base.PORTAL_COUNTRY.update({
    "QC_SEAO": "CA-QC",
    "SEAO": "CA-QC",
    "CA_SEAO": "CA-QC",
    "DK_UDBUD": "DK",
    "DK_UDBUD_DK": "DK",
    "FI_HILMA": "FI",
    "SI_EJN": "SI",
    "SI_EJN_PUBLIC": "SI",
    "ZA_ETENDERS": "ZA",
    "ZA_ETENDERS_OCDS": "ZA",
    "AU_AUSTENDER": "AU",
    "AUSTENDER": "AU",
})

# Specific jurisdictions must win before broad country metadata.  This matters
# for Scotland (often country=GB) and Quebec (often country=CA).
SPECIAL_PREFIXES = [
    ("UK_PCS_OCDS:", "GB-SCT"),
    ("uk_pcs_ocds:", "GB-SCT"),
    ("QC-", "CA-QC"),
    ("DK-", "DK"),
    ("FI-", "FI"),
    ("SI-", "SI"),
    ("ZA_", "ZA"),
    ("ZA-", "ZA"),
    ("AU-", "AU"),
]


def infer_country(rec: dict) -> str:
    # 1. Portal is the most authoritative jurisdiction signal for specialized
    # procurement systems and avoids Scotland/Quebec being swallowed by GB/CA.
    for raw in (
        rec.get("portal"), rec.get("portal_key"), rec.get("source"),
        rec.get("selection_portal"), rec.get("source_portal"),
    ):
        portal = str(raw or "").strip().upper()
        if portal in base.PORTAL_COUNTRY:
            return base.PORTAL_COUNTRY[portal]

    # 2. Candidate IDs are stable pipeline identifiers and frequently encode
    # the exact jurisdiction even when the buyer country is broad.
    cid = str(rec.get("candidate_id") or "")
    for prefix, code in SPECIAL_PREFIXES + base.PREFIX_COUNTRY:
        if cid.startswith(prefix):
            return code

    # 3. Fall back to explicit country metadata for ordinary national portals.
    for key in ("country_code", "country", "buyer_country", "iso_country", "jurisdiction_country"):
        code = base.norm_code(rec.get(key))
        if code:
            return code
    buyer = rec.get("buyer")
    if isinstance(buyer, dict):
        for key in ("country_code", "country", "countryCode", "iso_country"):
            code = base.norm_code(buyer.get(key))
            if code:
                return code
    return ""


base.infer_country = infer_country


if __name__ == "__main__":
    base.main()
