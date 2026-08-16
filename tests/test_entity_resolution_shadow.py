from pipeline.entity_resolution_shadow import (
    deterministic_links,
    normalize_be_enterprise_number,
    normalized_identity,
    splink_shadow_links,
)


def test_bce_number_normalization_is_strict():
    assert normalize_be_enterprise_number("BE 1001.050.094") == "1001050094"
    assert normalize_be_enterprise_number("BE1001050094") == "1001050094"
    assert normalize_be_enterprise_number("1001050094") == "1001050094"
    assert normalize_be_enterprise_number("2345678901") is None  # establishment-unit prefix
    assert normalize_be_enterprise_number("100105009") is None   # no guessed leading digit


def test_exact_bce_link_is_authoritative_and_auto_linkable():
    records = [
        {"id": "a", "country": "BE", "buyer": "SPM Business", "vat": "BE1001050094"},
        {"id": "b", "country": "Belgium", "name": "SPM BUSINESS", "enterprise_number": "1001.050.094"},
    ]
    links = deterministic_links(records)
    assert len(links) == 1
    assert links[0]["match_method"] == "EXACT_AUTHORITATIVE_LEGAL_ID"
    assert links[0]["canonical_legal_id"] == "BE:BCE:1001050094"
    assert links[0]["auto_merge_allowed"] is True


def test_similar_name_without_legal_id_never_auto_links():
    records = [
        {"id": "a", "country": "BE", "buyer": "Acme Brussels", "postcode": "1000"},
        {"id": "b", "country": "BE", "buyer": "ACME Brussels SA", "postcode": "1000"},
    ]
    assert deterministic_links(records) == []


def test_identity_preserves_raw_evidence():
    identity = normalized_identity({"id": "x", "country": "BE", "vat": "BE 1001.050.094", "buyer": "Example"})
    assert identity["legal_id_raw"] == "BE 1001.050.094"
    assert identity["canonical_legal_id"] == "BE:BCE:1001050094"


def test_splink_is_shadow_only_even_when_available_or_missing():
    records = [{"id": str(i), "buyer": f"Buyer {i}", "postcode": str(1000 + i)} for i in range(3)]
    result = splink_shadow_links(records)
    assert result["status"] in {"OPTIONAL_DEPENDENCY_MISSING", "INSUFFICIENT_TRAINING_CORPUS"}
    assert all(link.get("auto_merge_allowed") is False for link in result.get("links", []))
