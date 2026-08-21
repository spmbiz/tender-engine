import datetime as dt
import unittest

from pipeline.qwen_semantic_controller import decide


NOW = dt.datetime(2026, 8, 21, 16, 30, tzinfo=dt.timezone.utc)


def run(run_id, status, age, event="workflow_dispatch"):
    return {
        "databaseId": run_id,
        "status": status,
        "event": event,
        "createdAt": (NOW - dt.timedelta(minutes=age)).isoformat(),
    }


class QwenSemanticControllerTests(unittest.TestCase):
    def test_fresh_heartbeat_protects_old_running_worker(self):
        out = decide(
            now=NOW,
            remaining=95000,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 120)],
            heartbeats={1: {"state": "ok", "age_minutes": 2}},
        )
        self.assertEqual(out["running_keeper"]["id"], 1)
        self.assertEqual(out["cancel_ids"], [])
        self.assertFalse(out["need_dispatch"])

    def test_stale_heartbeat_recycles_worker(self):
        out = decide(
            now=NOW,
            remaining=95000,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 50)],
            heartbeats={1: {"state": "ok", "age_minutes": 31}},
        )
        self.assertIn(1, out["cancel_ids"])
        self.assertTrue(out["need_dispatch"])

    def test_missing_heartbeat_gets_startup_grace_only(self):
        young = decide(
            now=NOW,
            remaining=1,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 20)],
            heartbeats={1: {"state": "missing", "age_minutes": None}},
        )
        old = decide(
            now=NOW,
            remaining=1,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 36)],
            heartbeats={1: {"state": "missing", "age_minutes": None}},
        )
        self.assertIsNotNone(young["running_keeper"])
        self.assertIsNone(old["running_keeper"])
        self.assertTrue(old["need_dispatch"])

    def test_api_unknown_fails_safe_near_job_timeout(self):
        protected = decide(
            now=NOW,
            remaining=1,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 100)],
            heartbeats={1: {"state": "unknown", "age_minutes": None}},
        )
        expired = decide(
            now=NOW,
            remaining=1,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 146)],
            heartbeats={1: {"state": "unknown", "age_minutes": None}},
        )
        self.assertIsNotNone(protected["running_keeper"])
        self.assertIsNone(expired["running_keeper"])

    def test_queued_is_not_health_but_one_fresh_dispatch_can_wait(self):
        out = decide(
            now=NOW,
            remaining=95000,
            ledger_source=200,
            semantic_source=200,
            runs=[run(10, "queued", 2), run(11, "pending", 20)],
            heartbeats={},
        )
        self.assertEqual(out["queued_keeper"]["id"], 10)
        self.assertIn(11, out["cancel_ids"])
        self.assertFalse(out["need_dispatch"])

    def test_queued_debt_is_purged_when_worker_running(self):
        out = decide(
            now=NOW,
            remaining=95000,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 40), run(2, "queued", 1)],
            heartbeats={1: {"state": "ok", "age_minutes": 1}},
        )
        self.assertEqual(out["running_keeper"]["id"], 1)
        self.assertIn(2, out["cancel_ids"])

    def test_duplicate_running_workers_collapse_to_one(self):
        out = decide(
            now=NOW,
            remaining=95000,
            ledger_source=200,
            semantic_source=200,
            runs=[run(1, "in_progress", 20), run(2, "in_progress", 10)],
            heartbeats={1: {"state": "ok", "age_minutes": 5}, 2: {"state": "ok", "age_minutes": 1}},
        )
        self.assertEqual(out["running_keeper"]["id"], 2)
        self.assertIn(1, out["cancel_ids"])

    def test_newer_ledger_forces_new_generation_even_if_old_backlog_zero(self):
        out = decide(
            now=NOW,
            remaining=0,
            ledger_source=201,
            semantic_source=200,
            runs=[],
            heartbeats={},
        )
        self.assertTrue(out["source_gap"])
        self.assertTrue(out["has_backlog_or_new_source"])
        self.assertTrue(out["need_dispatch"])

    def test_zero_backlog_same_source_stays_idle(self):
        out = decide(
            now=NOW,
            remaining=0,
            ledger_source=200,
            semantic_source=200,
            runs=[],
            heartbeats={},
        )
        self.assertFalse(out["source_gap"])
        self.assertFalse(out["need_dispatch"])


if __name__ == "__main__":
    unittest.main()
