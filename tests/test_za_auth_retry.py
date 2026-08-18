import unittest

from pipeline.build_za_auth_retry import select


class ZaAuthRetryTests(unittest.TestCase):
    def test_selects_only_exact_za_authenticity_rows(self):
        payload = {"items": [
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-123", "portal": "ZA_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "ZA_ETENDERS_OCDS:wrong-prefix", "portal": "ZA_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "IE:two", "portal": "IRELAND_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-456", "portal": "ZA_ETENDERS", "review_stage": "BUSINESS_GATES"},
        ]}
        rows, stats = select(payload, 24)
        self.assertEqual([r["candidate_id"] for r in rows], ["ZA_ETENDERS_OCDS:ocds-9t57fa-123"])
        self.assertEqual(stats["za_rows_seen"], 2)

    def test_requires_official_portal_even_with_matching_id(self):
        payload = {"items": [
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-123", "portal": "GENERIC_PUBLIC_PAGE", "review_stage": "DCE_AUTHENTICITY"},
        ]}
        rows, _ = select(payload, 24)
        self.assertEqual(rows, [])

    def test_dedupes_and_respects_limit(self):
        payload = {"items": [
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-a", "portal": "ZA_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-a", "portal": "ZA_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-b", "portal": "ZA_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
        ]}
        rows, _ = select(payload, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["candidate_id"], "ZA_ETENDERS_OCDS:ocds-9t57fa-a")

    def test_never_selects_non_pending_state(self):
        payload = {"items": [
            {"candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-a", "portal": "ZA_ETENDERS", "state": "REVIEWED", "gate_readiness": False, "evidence_quality": "UNKNOWN_RETRIEVED_DOCUMENT"},
        ]}
        rows, _ = select(payload, 24)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
