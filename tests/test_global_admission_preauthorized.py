from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import global_admission as ga


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
        "last_decision": {"demand": {"hospitality": 100, "gws": 0, "tenders": 100}}
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
