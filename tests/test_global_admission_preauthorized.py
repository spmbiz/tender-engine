from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import global_admission as ga


@pytest.fixture(autouse=True)
def _neutralize_live_qwen_backlog(monkeypatch):
    # Existing fair-share tests should not inherit the repository's live backlog.
    # Reservation-specific tests override this explicitly.
    monkeypatch.setenv("QWEN_BACKLOG_REMAINING", "0")


def test_controller_fleet_branch_consumes_preapproved_budget_without_second_broker_vote(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "fleet-dce")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("preauthorized path must not query remote fair-share state")

    monkeypatch.setattr(ga, "_policy", explode)
    monkeypatch.setattr(ga, "_global_state", explode)
    monkeypatch.setattr(ga, "_repo_capacity_state", explode)

    allowed, report = ga.dynamic_tender_parallel(8)
    assert allowed == 8
    assert report["mode"] == "controller-preauthorized-budget"
    assert report["authority"] == "fleet_controller"


def test_preauthorized_budget_remains_hard_capped(monkeypatch):
    monkeypatch.setenv("DCE_ADMISSION_PREAUTHORIZED", "true")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    allowed, report = ga.dynamic_tender_parallel(999)
    assert allowed == 20
    assert report["hard_cap"] == 20


def test_manual_main_run_still_uses_broker(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)

    monkeypatch.setattr(ga, "_policy", lambda: {
        "github": {"capacity": 20},
        "workloads": {
            "hospitality": {"enabled": True, "weight": 0.50, "min_slots_when_demanding": 6, "max_slots": 20},
            "tenders": {"enabled": True, "weight": 0.25, "min_slots_when_demanding": 4, "max_slots": 20},
            "gws": {"enabled": True, "weight": 0.25, "min_slots_when_demanding": 4, "max_slots": 10},
        },
    })
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 6, "gws": 0, "tenders": 100}}
    })

    def fake_repo_state(repo, ignore_run_id=""):
        if repo == ga.GLOBAL_REPO:
            from collections import Counter
            return Counter({"hospitality": 6}), Counter()
        from collections import Counter
        return Counter({"tenders": 10}), Counter()

    monkeypatch.setattr(ga, "_repo_capacity_state", fake_repo_state)
    allowed, report = ga.dynamic_tender_parallel(8)
    assert report["mode"] == "active-slot-fair-share-admission"
    assert allowed == 4


def _burst_policy():
    return {
        "github": {"capacity": 20},
        "workloads": {
            "hospitality": {"enabled": False, "weight": 0.0, "min_slots_when_demanding": 0, "max_slots": 0},
            "tenders": {"enabled": True, "weight": 0.5, "min_slots_when_demanding": 10, "max_slots": 20},
            "gws": {"enabled": True, "weight": 0.5, "min_slots_when_demanding": 10, "max_slots": 10},
        },
    }


def test_tenders_borrow_all_idle_sibling_slots_without_preemption(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)
    monkeypatch.setattr(ga, "_policy", _burst_policy)
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 0, "gws": 0, "tenders": 100}}
    })

    from collections import Counter
    monkeypatch.setattr(ga, "_repo_capacity_state", lambda repo, ignore_run_id="": (Counter(), Counter()))
    allowed, report = ga.dynamic_tender_parallel(60)
    assert allowed == 20
    assert report["tender_floor"] == 10
    assert report["tender_max"] == 20
    assert report["borrowed_idle_slots_after_admission"] == 10
    assert report["sibling_missing_reserved"] == 0


def test_gws_demand_reinstates_its_ten_slot_reservation(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)
    monkeypatch.setattr(ga, "_policy", _burst_policy)
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 0, "gws": 10, "tenders": 100}}
    })

    from collections import Counter
    monkeypatch.setattr(ga, "_repo_capacity_state", lambda repo, ignore_run_id="": (Counter(), Counter()))
    allowed, report = ga.dynamic_tender_parallel(60)
    assert allowed == 10
    assert report["sibling_targets"]["gws"] == 10
    assert report["sibling_missing_reserved"] == 10
    assert report["borrowed_idle_slots_after_admission"] == 0


def test_existing_gws_activity_counts_as_consumed_not_double_reserved(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)
    monkeypatch.setattr(ga, "_policy", _burst_policy)
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 0, "gws": 10, "tenders": 100}}
    })

    def fake_repo_state(repo, ignore_run_id=""):
        from collections import Counter
        if repo == ga.GLOBAL_REPO:
            return Counter({"gws": 6}), Counter()
        return Counter(), Counter()

    monkeypatch.setattr(ga, "_repo_capacity_state", fake_repo_state)
    allowed, report = ga.dynamic_tender_parallel(60)
    assert allowed == 10
    assert report["physical_free"] == 14
    assert report["sibling_missing_reserved"] == 4
    assert report["global_room_after_protection"] == 10


def test_repo_capacity_state_requests_up_to_100_runs_and_jobs(monkeypatch):
    urls = []

    def fake_json(url, default):
        urls.append(url)
        if "/actions/runs?" in url and "status=in_progress" in url:
            return {
                "workflow_runs": [{
                    "id": 123,
                    "name": "Qwen Live Notice Classification",
                    "path": ".github/workflows/qwen-live-classification.yml",
                    "jobs_url": "https://api.github.com/repos/walidgdg1-ai/tender-engine/actions/runs/123/jobs",
                }]
            }
        if "/actions/runs?" in url:
            return {"workflow_runs": []}
        if "/actions/runs/123/jobs" in url:
            return {"jobs": [{"status": "in_progress"} for _ in range(20)]}
        return default

    monkeypatch.setattr(ga, "_json", fake_json)
    active, queued = ga._repo_capacity_state(ga.TENDER_REPO)
    assert active["qwen-semantic"] == 20
    assert active["tenders"] == 0
    assert queued["qwen-semantic"] == 0
    assert any("status=in_progress&per_page=100" in u for u in urls)
    assert any("/actions/runs/123/jobs?per_page=100" in u for u in urls)


def test_per_page_preserves_existing_query_and_clamps_to_100():
    assert ga._per_page("https://api.github.com/x/jobs?filter=latest", 1000).endswith("filter=latest&per_page=100")


def test_high_qwen_backlog_reserves_sixteen_slots_from_general_tender_work(monkeypatch):
    monkeypatch.setenv("QWEN_BACKLOG_REMAINING", "90000")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Tender General Maintenance")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)
    monkeypatch.setattr(ga, "_policy", _burst_policy)
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 0, "gws": 0, "tenders": 100}}
    })
    from collections import Counter
    monkeypatch.setattr(ga, "_repo_capacity_state", lambda repo, ignore_run_id="": (Counter(), Counter()))

    allowed, report = ga.dynamic_tender_parallel(20)
    assert allowed == 4
    assert report["qwen_semantic_reservation_target"] == 16
    assert report["qwen_missing_reserved"] == 16
    assert report["admission_room_after_qwen_reservation"] == 4


def test_qwen_semantic_lane_can_consume_reserved_and_idle_tender_capacity(monkeypatch):
    monkeypatch.setenv("QWEN_BACKLOG_REMAINING", "90000")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Qwen Live Notice Classification")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)
    monkeypatch.setattr(ga, "_policy", _burst_policy)
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 0, "gws": 0, "tenders": 100}}
    })
    from collections import Counter
    monkeypatch.setattr(ga, "_repo_capacity_state", lambda repo, ignore_run_id="": (Counter(), Counter()))

    allowed, report = ga.dynamic_tender_parallel(20)
    assert allowed == 20
    assert report["sublane"] == "qwen-semantic"
    assert report["qwen_semantic_reservation_target"] == 16
    assert report["admission_room_after_qwen_reservation"] == 20


def test_existing_qwen_workers_satisfy_reservation_and_dce_stays_thin(monkeypatch):
    monkeypatch.setenv("QWEN_BACKLOG_REMAINING", "90000")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Qwen DCE Triage")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.delenv("DCE_ADMISSION_PREAUTHORIZED", raising=False)
    monkeypatch.delenv("DCE_DISABLE_GLOBAL_ADMISSION", raising=False)
    monkeypatch.setattr(ga, "_policy", _burst_policy)
    monkeypatch.setattr(ga, "_global_state", lambda: {
        "last_decision": {"demand": {"hospitality": 0, "gws": 0, "tenders": 100}}
    })
    from collections import Counter

    def fake_repo_state(repo, ignore_run_id=""):
        if repo == ga.TENDER_REPO:
            return Counter({"qwen-semantic": 16}), Counter()
        return Counter(), Counter()

    monkeypatch.setattr(ga, "_repo_capacity_state", fake_repo_state)
    allowed, report = ga.dynamic_tender_parallel(20)
    assert allowed == 2
    assert report["dce_backfill_cap"] == 2
    assert report["existing_qwen_semantic_active"] == 16
    assert report["qwen_missing_reserved"] == 0


def test_tender_repo_workload_classifier_separates_qwen_from_general_tenders():
    assert ga._classify(
        ga.TENDER_REPO,
        "Qwen Live Notice Classification",
        ".github/workflows/qwen-live-classification.yml",
    ) == "qwen-semantic"
    assert ga._classify(
        ga.TENDER_REPO,
        "Qwen DCE Triage",
        ".github/workflows/qwen-dce-triage.yml",
    ) == "tenders"
