from __future__ import annotations

from pipeline.publish_supergreen_hot import merge_review, spm_post_dce_rank


def _row(title: str, *, coverage: int = 10, deadline_resolved: bool = True, text: str = "", priority: int = 80):
    return {
        "candidate_id": title,
        "title": title,
        "deadline": "2026-09-01",
        "deadline_resolved": deadline_resolved,
        "evidence_gate_coverage": coverage,
        "priority_score": priority,
        "evidence_by_gate": {"deliverables_scope": [{"text": text}]},
        "hot_ready_at": "2026-08-16T00:00:00+00:00",
    }


def test_clear_web_beats_high_coverage_federal_operations_contract():
    web = _row("Public website redesign and CMS migration", coverage=9, deadline_resolved=False, text="Remote delivery accepted")
    medicare = _row(
        "Medicare Administrative Contractor support services",
        coverage=14,
        text="FISMA protected health information business associate agreement 24/7 application support",
        priority=89,
    )
    assert spm_post_dce_rank(web)[0] > spm_post_dce_rank(medicare)[0]
    assert spm_post_dce_rank(web)[1] == "HOT"


def test_digital_training_is_preserved_as_good_candidate():
    training = _row("Digital training and e-learning content services", coverage=8, text="online delivery", priority=72)
    assert spm_post_dce_rank(training)[1] in {"HOT", "GOOD"}


def test_us_citizen_top_secret_rfi_is_deprioritized_not_deleted():
    rfi = _row(
        "Joint Targeting Toolbox software development RFI",
        coverage=14,
        priority=89,
        text=(
            "THIS NOTICE IS NOT A REQUEST FOR PROPOSAL. No award will be made. "
            "All employees involved in the project must be U.S. Citizens. "
            "Top Secret clearance and SCI eligible."
        ),
    )
    score, band, _, blockers = spm_post_dce_rank(rfi)
    assert score < 20
    assert band == "LOW"
    assert "us-citizens-only" in blockers


def test_exploration_lane_preserves_low_ranked_evidence_rich_rows():
    rows = [
        _row("Public website redesign and CMS migration", coverage=9, deadline_resolved=False),
        _row("Digital training and e-learning content services", coverage=8, priority=72),
        _row("Medicare Administrative Contractor support services", coverage=14, text="FISMA protected health information business associate agreement 24/7", priority=89),
        _row("Joint Targeting Toolbox software development RFI", coverage=14, text="No award will be made. must be U.S. Citizens. Top Secret clearance", priority=89),
    ]
    out = merge_review({"latest_dce_run_id": 1, "items": rows}, [], set(), "1", "3", 4)
    assert len(out["items"]) == 4
    assert out["items"][0]["candidate_id"] == "Public website redesign and CMS migration"
    assert any(row["review_lane"] == "EXPLORATION" for row in out["items"])
