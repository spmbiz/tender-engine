from __future__ import annotations

import json

import dce_worker as base
import dce_worker_v22 as v22


def main() -> None:
    assert base.ADAPTERS.get("FR_BOAMP") is v22.adapter_fr_boamp_v22
    assert v22.portal_for_fr_url_v22("https://www.marches-publics.gouv.fr/entreprise/consultation/123") == "FR_PLACE"
    assert v22.portal_for_fr_url_v22("https://foo.achatpublic.com/sdm/ent/gen/ent_detail.do") == "FR_ACHATPUBLIC"
    assert v22.portal_for_fr_url_v22("https://paysdefalaise.e-marchespublics.com/pack/annonce_marche_public_1_123.html") == "FR_E_MARCHESPUBLICS"
    assert v22.portal_for_fr_url_v22("https://www.marches-securises.fr/perso/foo/") == "FR_MARCHES_SECUR"

    html = '''
    <div><span>Adresse internet :</span>
      <a href="https://www.eureennormandie.fr/">buyer home</a></div>
    <div><span>Adresse internet du profil d'acheteur :</span>
      <a href="https://www.marches-publics.gouv.fr/entreprise/consultation/123">profil</a></div>
    <div><span>Autre moyen d'accès aux documents de la consultation :</span>
      <a href="https://paysdefalaise.e-marchespublics.com/pack/annonce_marche_public_1_456.html">DCE</a></div>
    <a href="https://www.boamp.fr/avis/detail/26-123">BOAMP notice</a>
    '''
    links = v22.extract_boamp_downstream_links(html, "https://www.boamp.fr/avis/detail/26-123")
    urls = [x["url"] for x in links]
    assert "https://www.marches-publics.gouv.fr/entreprise/consultation/123" in urls
    assert "https://paysdefalaise.e-marchespublics.com/pack/annonce_marche_public_1_456.html" in urls
    assert "https://www.boamp.fr/avis/detail/26-123" not in urls
    assert "https://www.eureennormandie.fr/" not in urls, urls
    assert links[0]["portal"] in {"FR_PLACE", "FR_E_MARCHESPUBLICS"}

    # The official dataset commonly stores the full notice as JSON-encoded
    # `donnees`. Structural key names must carry the semantic context.
    record = {
        "idweb": "26-123",
        "donnees": json.dumps({
            "ANNONCE": {
                "ACHETEUR": {"URL": "https://buyer.example.fr/"},
                "COMMUNICATION": {
                    "URL_PROFIL_ACHETEUR": "https://foo.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=CSL_2026_abc",
                    "LIEN_DIRECT_DOCUMENTS_CONSULTATION": "https://www.marches-publics.gouv.fr/entreprise/consultation/987",
                },
            }
        }),
    }
    structured = v22.extract_boamp_structured_links(record)
    s_urls = [x["url"] for x in structured]
    assert "https://foo.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=CSL_2026_abc" in s_urls
    assert "https://www.marches-publics.gouv.fr/entreprise/consultation/987" in s_urls
    assert "https://buyer.example.fr/" not in s_urls

    # An unknown host is accepted only when the BOAMP field explicitly says it is
    # the buyer profile / consultation-document route.
    unknown = v22.extract_boamp_downstream_links(
        '<span>Adresse internet du profil d\'acheteur :</span><a href="https://procurement.example.fr/tender/42">go</a>'
    )
    assert unknown and unknown[0]["portal"] == "GENERIC_PUBLIC_PAGE"
    noise = v22.extract_boamp_downstream_links('<span>Adresse internet :</span><a href="https://buyer.example.fr/">home</a>')
    assert noise == []

    assert v22._candidate_idweb({"candidate_id": "FR-BOAMP:26-81370"}) == "26-81370"
    print({"worker": "v22", "boamp_router": True, "profile_links": len(links), "structured_links": len(structured), "status": "ok"})


if __name__ == "__main__":
    main()
