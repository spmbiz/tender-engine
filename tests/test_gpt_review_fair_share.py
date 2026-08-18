from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import rebuild_gpt_review_bank_from_release as bank
import refresh_gpt_inbox_live as inbox


def row(i: int, *, band: str, stage: str = "BUSINESS_GATES", portal: str = "TED", score: int = 70):
    return {
        "candidate_id": f"{portal}:{i}",
        "title": f"Candidate {i}",
        "deadline": "2099-12-31T12:00:00+00:00",
        "portal": portal,
        "review_stage": stage,
        "gate_readiness": stage != "DCE_AUTHENTICITY",
        "evidence_gate_coverage": 5 if stage != "DCE_AUTHENTICITY" else 0,
        "spm_fit_band": band,
        "spm_post_dce_score": score,
        "gpt_priority_score": score,
        "priority_score": score,
        "source_dce_run_id": 1000 + i,
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "evidence_quality_summary": {"raw_status": "DOWNLOADED_PUBLIC", "documents_with_text": 2, "text_chars": 5000},
    }


def build_population():
    rows = []
    for i in range(180):
        band = "HOT" if i < 10 else "GOOD" if i < 60 else "MAYBE"
        rows.append(row(i, band=band, portal=("TED", "US_SAM", "FR", "IE")[i % 4], score=95 - (i % 40)))
    for i in range(60):
        rows.append(row(1000 + i, band="LOW", stage="DCE_AUTHENTICITY", portal=("TED", "US_SAM", "FR", "IE", "DE")[i % 5], score=35))
    for i in range(160):
        rows.append(row(2000 + i, band="LOW", portal=("TED", "US_SAM", "FR", "IE", "DE", "ES")[i % 6], score=20))
    return rows


def test_recovered_hot_window_reserves_priority_authenticity_and_low_surveillance():
    selected, metrics = bank.select_hot_window(build_population(), 160)
    lanes = Counter(x.get("review_lane") for x in selected)
    assert len(selected) == 160
    assert lanes["SPM_PRIORITY"] == 120
    assert lanes["DCE_AUTHENTICITY_REPAIR"] == 20
    assert lanes["LOW_PORTAL_SURVEILLANCE"] == 20
    low_portals = {x["portal"] for x in selected if x.get("review_lane") == "LOW_PORTAL_SURVEILLANCE"}
    auth_portals = {x["portal"] for x in selected if x.get("review_lane") == "DCE_AUTHENTICITY_REPAIR"}
    assert len(low_portals) >= 4
    assert len(auth_portals) >= 4
    assert metrics["selected_by_lane"]["LOW_PORTAL_SURVEILLANCE"] == 20


def test_final_inbox_does_not_destroy_fair_share_on_second_cap():
    population = build_population()
    selected, metrics = inbox.select_inbox_window(population, 160)
    lanes = Counter(x.get("inbox_lane") for x in selected)
    assert len(selected) == 160
    assert lanes["GPT_PRIORITY"] == 120
    assert lanes["DCE_AUTHENTICITY_REPAIR"] == 20
    assert lanes["LOW_PORTAL_SURVEILLANCE"] == 20
    assert metrics["selected_by_lane"]["GPT_PRIORITY"] == 120
    assert metrics["selected_by_lane"]["DCE_AUTHENTICITY_REPAIR"] == 20
    assert metrics["selected_by_lane"]["LOW_PORTAL_SURVEILLANCE"] == 20
