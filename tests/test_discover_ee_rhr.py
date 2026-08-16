from datetime import datetime, timezone

from pipeline.discover_ee_rhr import parse_bulk


def test_estonia_rhr_parser_preserves_authoritative_ids_and_routes():
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<OPEN-DATA
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:efac="http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1">
 <ContractNotice>
  <cbc:ID schemeName="notice-id">notice-uuid-1</cbc:ID>
  <cbc:ContractFolderID>PROCEDURE-42</cbc:ContractFolderID>
  <cbc:IssueDate>2026-08-15+03:00</cbc:IssueDate>
  <cbc:ProcedureCode>open</cbc:ProcedureCode>
  <efac:NoticeSubType><cbc:SubTypeCode>17</cbc:SubTypeCode></efac:NoticeSubType>
  <efac:Organization><efac:Company>
    <cac:PartyName><cbc:Name>Tallinn Buyer</cbc:Name></cac:PartyName>
    <cac:PartyLegalEntity><cbc:CompanyID>12345678</cbc:CompanyID></cac:PartyLegalEntity>
  </efac:Company></efac:Organization>
  <cac:ProcurementProject>
    <cbc:Name>Digital service</cbc:Name>
    <cbc:Description>Build a public digital service</cbc:Description>
    <cbc:ItemClassificationCode>72200000</cbc:ItemClassificationCode>
  </cac:ProcurementProject>
  <cbc:EstimatedOverallContractAmount currencyID="EUR">125000</cbc:EstimatedOverallContractAmount>
  <cac:TenderSubmissionDeadlinePeriod>
    <cbc:EndDate>2099-09-01+03:00</cbc:EndDate><cbc:EndTime>12:00:00+03:00</cbc:EndTime>
  </cac:TenderSubmissionDeadlinePeriod>
  <cac:CallForTendersDocumentReference><cbc:URI>https://riigihanked.riik.ee/rhr-web/#/procurement/8188124/documents?group=B</cbc:URI></cac:CallForTendersDocumentReference>
 </ContractNotice>
</OPEN-DATA>'''
    rows = parse_bulk(xml, datetime.now(timezone.utc).isoformat())
    assert len(rows) == 1
    rec = rows[0]
    assert rec["candidate_id"] == "EE-RHR:notice-uuid-1"
    assert rec["procedure_id"] == "PROCEDURE-42"
    assert rec["rhr_id"] == "8188124"
    assert rec["buyer_registration_id"] == "12345678"
    assert rec["cpv"] == ["72200000"]
    assert rec["estimated_value"] == 125000.0
    assert rec["route"]["route_status"] == "RHR_DOCUMENT_ROUTE_DISCOVERED"
    assert rec["current"] is True


def test_non_biddable_notice_subtype_is_not_promoted():
    xml = b'''<OPEN-DATA
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:efac="http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1">
 <ContractNotice><cbc:ID schemeName="notice-id">award-like</cbc:ID><efac:NoticeSubType><cbc:SubTypeCode>29</cbc:SubTypeCode></efac:NoticeSubType></ContractNotice>
 </OPEN-DATA>'''
    assert parse_bulk(xml, "2026-08-16T00:00:00+00:00") == []
