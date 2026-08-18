import unittest

from pipeline.build_estonia_auth_retry import select


class EstoniaAuthRetryTests(unittest.TestCase):
    def test_selects_only_exact_estonia_authenticity_rows(self):
        payload = {
            "items": [
                {"candidate_id": "EE-RHR:one", "portal": "EE_RHR", "review_stage": "DCE_AUTHENTICITY"},
                {"candidate_id": "IE:two", "portal": "IRELAND_ETENDERS", "review_stage": "DCE_AUTHENTICITY"},
                {"candidate_id": "EE-RHR:three", "portal": "EE_RHR", "review_stage": "BUSINESS_GATES"},
            ]
        }
        rows, stats = select(payload, 24)
        self.assertEqual([r["candidate_id"] for r in rows], ["EE-RHR:one"])
        self.assertEqual(stats["estonia_rows_seen"], 2)

    def test_dedupes_and_respects_limit(self):
        payload = {"items": [
            {"candidate_id": "EE-RHR:a", "portal": "EE_RHR", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "EE-RHR:a", "portal": "EE_RHR", "review_stage": "DCE_AUTHENTICITY"},
            {"candidate_id": "EE-RHR:b", "portal": "EE_RHR", "review_stage": "DCE_AUTHENTICITY"},
        ]}
        rows, _ = select(payload, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["candidate_id"], "EE-RHR:a")

    def test_never_selects_non_pending_state(self):
        payload = {"items": [
            {"candidate_id": "EE-RHR:a", "portal": "EE_RHR", "state": "REVIEWED", "gate_readiness": False, "evidence_quality": "UNKNOWN_RETRIEVED_DOCUMENT"},
        ]}
        rows, _ = select(payload, 24)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
