from __future__ import annotations

import xml.etree.ElementTree as ET

import placsp_atom

ATOM = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
      xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2">
  <entry>
    <id>https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/20305317</id>
    <title>Servicio digital</title>
    <cac-place-ext:ContractFolderStatus>
      <cbc:ContractFolderID>2026/0012</cbc:ContractFolderID>
      <cac:LegalDocumentReference>
        <cbc:ID>PCAP.pdf</cbc:ID>
        <cac:Attachment><cac:ExternalReference>
          <cbc:URI>https://contrataciondelestado.es/wps/wcm/connect/PLACE_es/Site/area/docAccCmpnt?srv=cmpnt&amp;cmpntname=GetDocumentsById&amp;source=library&amp;DocumentIdParam=11111111-1111-1111-1111-111111111111</cbc:URI>
        </cac:ExternalReference></cac:Attachment>
      </cac:LegalDocumentReference>
      <cac:TechnicalDocumentReference>
        <cbc:ID>PPT.pdf</cbc:ID>
        <cac:Attachment><cac:ExternalReference>
          <cbc:URI>https://contrataciondelestado.es/wps/wcm/connect/PLACE_es/Site/area/docAccCmpnt?srv=cmpnt&amp;cmpntname=GetDocumentsById&amp;source=library&amp;DocumentIdParam=22222222-2222-2222-2222-222222222222</cbc:URI>
        </cac:ExternalReference></cac:Attachment>
      </cac:TechnicalDocumentReference>
      <cac:AdditionalDocumentReference>
        <cbc:ID>Anexo</cbc:ID>
        <cac:Attachment><cac:ExternalReference>
          <cbc:URI>https://contrataciondelestado.es/files/anexo.pdf</cbc:URI>
        </cac:ExternalReference></cac:Attachment>
      </cac:AdditionalDocumentReference>
    </cac-place-ext:ContractFolderStatus>
  </entry>
  <link rel="next" href="next-page.atom" />
</feed>
'''


def main() -> None:
    root = ET.fromstring(ATOM)
    entries = placsp_atom.entries(root)
    assert len(entries) == 1
    entry = entries[0]

    assert placsp_atom.candidate_id(entry) == (
        "ES-PLACSP:https:_contrataciondelestado.es_sindicacion_"
        "licitacionesPerfilContratante_20305317"
    )
    assert placsp_atom.contract_folder_id(entry) == "2026/0012"

    urls = placsp_atom.document_urls(entry)
    assert len(urls) == 3, urls
    assert sum("GetDocumentsById" in u for u in urls) == 2, urls
    assert any(u.endswith("anexo.pdf") for u in urls), urls
    assert all("detalle_licitacion" not in u for u in urls), urls

    nxt = placsp_atom.next_link(root, "https://example.test/current.atom")
    assert nxt == "https://example.test/next-page.atom", nxt
    print({"placsp_document_urls": len(urls), "extensionless": 2, "status": "ok"})


if __name__ == "__main__":
    main()
