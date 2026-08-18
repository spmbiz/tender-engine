from __future__ import annotations

import xml.etree.ElementTree as ET

import dce_worker as base
import dce_worker_v22 as v22


def test_transport_hygiene_examples():
    bad = [
        ("ionicons.ttf", "https://eojn.hr/fonts/ionicons.ttf?v=2.0.0", "application/octet-stream"),
        ("rozamunde1.png", "https://example.blob.core.windows.net/public-resources/x/rozamunde1.png", "application/octet-stream"),
        ("rib-tender-nutzungsbedingungen-05-2026.pdf", "https://www.rib-software.com/pdf/de/rib-tender-nutzungsbedingungen-05-2026.pdf", "application/pdf"),
        ("depot-pli.pdf", "https://www.marches-publics.info/kiosque/depot-pli.pdf", "application/pdf"),
        ("en_AGB_subreport.pdf", "https://www.subreport-elvis.de/docs/vertraege/en_AGB_subreport.pdf", "application/pdf"),
    ]
    for name, url, ct in bad:
        blocked, reason = v22._obvious_non_dce_name_or_url(name, url, ct)
        assert blocked, (name, reason)

    good = [
        ("18_ZP_2026 SWZ.pdf", "https://platformazakupowa.pl/file/get_new/a.pdf", "application/pdf"),
        ("Vergabeunterlagen_CXP4Y4VMUCC.zip", "https://www.dtvp.de/Satellite/public/project/documents/a.zip", "application/zip"),
        ("Dossier_de_consultation.zip", "https://www.marches-publics.gouv.fr/download/123", "application/octet-stream"),
    ]
    for name, url, ct in good:
        blocked, reason = v22._obvious_non_dce_name_or_url(name, url, ct)
        assert not blocked, (name, reason)


def test_manifest_hygiene_downgrades_false_transport_success():
    manifest = {
        "status": "DOWNLOADED_PUBLIC",
        "files": [
            {
                "name": "depot-pli.pdf",
                "source_url": "https://www.marches-publics.info/kiosque/depot-pli.pdf",
                "content_type": "application/pdf",
            }
        ],
    }
    assert v22._sanitize_manifest_files(manifest) == 1
    assert manifest["status"] == "GENERIC_PUBLIC_PAGE_UNRESOLVED"
    assert manifest["files"] == []
    assert len(manifest["transport_rejected_files"]) == 1


def test_manifest_hygiene_keeps_real_dce_with_side_asset():
    manifest = {
        "status": "DOWNLOADED_PUBLIC",
        "files": [
            {"name": "SWZ.pdf", "source_url": "https://example.test/SWZ.pdf", "content_type": "application/pdf"},
            {"name": "ionicons.ttf", "source_url": "https://example.test/fonts/ionicons.ttf", "content_type": "application/octet-stream"},
        ],
    }
    assert v22._sanitize_manifest_files(manifest) == 1
    assert manifest["status"] == "DOWNLOADED_PUBLIC"
    assert [x["name"] for x in manifest["files"]] == ["SWZ.pdf"]


def test_auth_redirect_refinement():
    manifest = {
        "status": "GENERIC_PUBLIC_PAGE_UNRESOLVED",
        "files": [],
        "dce_method_attempts": [
            {"resolved_url": "https://tendsign.com/login.aspx?URL=s_meformsnotice.aspx"}
        ],
    }
    assert v22._refine_auth_from_redirect(manifest)
    assert manifest["status"] == "AUTH_REQUIRED"


def test_link_selection_requires_specificity():
    candidate = {"title": "Maintenance of municipal digital archive platform", "buyer": "Example City"}
    rows = [
        {"href": "https://example.test/1", "text": "Road resurfacing and drainage works"},
        {"href": "https://example.test/2", "text": "Example City - Maintenance of municipal digital archive platform"},
    ]
    chosen, scored = v22._pick_best_link(rows, candidate)
    assert chosen == "https://example.test/2"
    assert scored[0]["href"] == chosen


def test_place_specific_route_from_url():
    candidate = {
        "route": {"detail_url": "https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/2888917?orgAcronyme=x7c"}
    }
    route = v22._place_specific_route(candidate)
    assert route
    assert route["consultation_id"] == "2888917"
    assert route["org_acronym"] == "x7c"


def test_placsp_exact_title_buyer_match():
    entry = ET.fromstring(
        """
        <entry xmlns:cac='urn:test:cac' xmlns:cbc='urn:test:cbc'>
          <cbc:Name>Servicio de mantenimiento de plataforma digital</cbc:Name>
          <cbc:BuyerName>Ayuntamiento de Prueba</cbc:BuyerName>
          <cbc:ContractFolderID>2026/ABC</cbc:ContractFolderID>
        </entry>
        """
    )
    candidate = {
        "candidate_id": "TED:123456-2026",
        "title": "Servicio de mantenimiento de plataforma digital",
        "buyer": "Ayuntamiento de Prueba",
        "route": {},
    }
    matched, method = v22.entry_match_v22(entry, candidate)
    assert matched
    assert method == "exact_title_buyer_v22"


def test_v22_adapters_registered():
    assert base.ADAPTERS["FR_PLACE"] is v22.adapter_place_v22
    assert base.ADAPTERS["CZ_NIPEZ"] is v22.adapter_nen_v22
    assert base.ADAPTERS["CZ_NIPEZ_PUBLIC"] is v22.adapter_nen_v22


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} V22 tests")
