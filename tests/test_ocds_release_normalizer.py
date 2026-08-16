from datetime import datetime, timezone

from pipeline.ocds_release_normalizer import release_awards, release_to_candidate


def fixture_release():
    return {
        "ocid":"ocds-test-123",
        "id":"release-1",
        "date":"2026-08-15T10:00:00Z",
        "buyer":{"id":"BUY-1","name":"Buyer One"},
        "parties":[{"id":"BUY-1","name":"Buyer One","contactPoint":{"email":"buyer@example.test"}}],
        "tender":{
            "title":"Managed web services",
            "description":"Build and operate a public website",
            "status":"active",
            "procurementMethod":"open",
            "value":{"amount":100000,"currency":"EUR"},
            "tenderPeriod":{"endDate":"2099-09-01T12:00:00Z"},
            "classification":{"id":"72413000"},
            "documents":[{"id":"d1","title":"Bid pack","url":"https://example.test/bid.zip","format":"application/zip"}],
            "tenderers":[{"id":"T1","name":"A"},{"id":"T2","name":"B"}],
        },
        "awards":[{"id":"A1","status":"active","value":{"amount":90000,"currency":"EUR"},"suppliers":[{"id":"S1","name":"Supplier One"}]}],
    }


def test_candidate_keeps_documents_and_observed_tenderer_count():
    rec=release_to_candidate(fixture_release(),source="TEST",portal="TEST",notice_url="https://example.test/notice",now=datetime(2026,8,16,tzinfo=timezone.utc))
    assert rec is not None
    assert rec["current"] is True
    assert rec["cpv"] == ["72413000"]
    assert rec["tenderers_received_observed"] == 2
    assert rec["route"]["document_urls"] == ["https://example.test/bid.zip"]
    assert rec["buyer_contact"]["email"] == "buyer@example.test"


def test_award_supplier_link_is_separate_from_live_candidate():
    rows=release_awards(fixture_release(),source="TEST",portal="TEST",notice_url="https://example.test/notice")
    assert len(rows)==1
    assert rows[0]["grain"]=="AWARD"
    assert rows[0]["supplier_id"]=="S1"
    assert rows[0]["tenderers_received_observed"]==2
