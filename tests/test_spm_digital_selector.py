from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from auto_select_dce import business_fit, retrieval_score, select


def rec(cid, title, description="", portal="TEST", cpv=None, naics=None):
    row = {
        "candidate_id": cid,
        "title": title,
        "description": description,
        "buyer": "Public Buyer",
        "portal": portal,
        "deadline": "2099-09-30T12:00:00+00:00",
        "current": True,
    }
    if cpv:
        row["cpv"] = cpv
    if naics:
        row["naics"] = naics
    return row


def test_core_digital_and_middleman_scopes_pass():
    samples = [
        rec("X:1", "Redesign and development of the public authority website"),
        rec("X:2", "Graphic design and layout of annual reports"),
        rec("X:3", "Video editing and motion graphics production"),
        rec("X:4", "Transcription, subtitling and captioning services"),
        rec("X:5", "Printing services for brochures and leaflets"),
        rec("X:6", "Workflow automation and API integration development"),
        rec("X:7", "Social media content production and digital marketing"),
    ]
    for row in samples:
        ok, fit_class, fit_score, _ = business_fit(row)
        assert ok, (row["title"], fit_class)
        assert fit_score >= 70


def test_digital_training_web_portal_and_ambiguous_it_are_kept_for_dce():
    samples = [
        rec("R:1", "Digital skills training workshops for young people"),
        rec("R:2", "Development and support of a new web portal"),
        rec("R:3", "IT services and managed application support"),
        rec("R:4", "Cloud platform and software services"),
        rec("R:5", "Digital transformation consulting services"),
    ]
    for row in samples:
        ok, fit_class, fit_score, reasons = business_fit(row)
        assert ok, (row["title"], fit_class, reasons)
        assert fit_score >= 45


def test_broad_cpv_preserves_non_english_it_recall():
    row = rec("CPV:1", "Refonte du service numérique institutionnel", cpv="72200000")
    ok, fit_class, fit_score, _ = business_fit(row)
    assert ok
    assert fit_class in {"SPM_SOFTWARE_AUTOMATION", "SPM_IT_POTENTIAL"}
    assert fit_score >= 60


def test_portal_yield_can_never_rescue_totally_irrelevant_candidate():
    row = rec("R:Y", "Supply of office chairs", portal="EASY_PORTAL")
    performance = {
        "portals": {
            "EASY_PORTAL": {
                "candidates": 1000,
                "smoothed_useful_rate": 0.99,
                "auth_rate": 0.0,
                "generic_or_unresolved_rate": 0.0,
            }
        }
    }
    score, reasons = retrieval_score(row, performance)
    assert score == -100
    assert any("reject:" in r for r in reasons)
    assert select([row], minimum=0, limit=100, portal_performance=performance) == []


def test_narrow_cpv_can_rescue_non_english_web_notice():
    row = rec("CPV:2", "Refonte du service numérique institutionnel", cpv="72413000")
    ok, fit_class, fit_score, _ = business_fit(row)
    assert ok
    assert fit_class == "SPM_WEB"
    assert fit_score >= 80


def test_output_persists_fit_class_and_score():
    row = rec("O:1", "Website redesign and CMS migration")
    selected = select([row], minimum=0, limit=10)
    assert len(selected) == 1
    assert selected[0]["selection_fit_class"] == "SPM_WEB"
    assert selected[0]["business_fit_score"] >= 80
    assert selected[0]["preliminary_score"] <= 89


def test_sam_hardware_boilerplate_cannot_fake_web_or_print_fit():
    boilerplate = (
        "Contractors may view orders in the PIEE website. Department of Defense specifications "
        "are available from Navy Publishing and Printing Service."
    )
    row = rec(
        "SAM:JUNK",
        "TRANSMITTER,PRESSUR",
        description=boilerplate,
        portal="US_SAM",
        naics="334513",
    )
    ok, fit_class, score, reasons = business_fit(row)
    assert not ok
    assert fit_class == "REJECT_SAM_PHYSICAL_COMMODITY"
    assert score == -100
    assert any("sam-physical" in r for r in reasons)


def test_sam_real_software_scope_with_service_naics_can_pass():
    row = rec(
        "SAM:SOFT",
        "Water Management Programming",
        description="Software analysis, database development, web development and systems integration.",
        portal="US_SAM",
        naics="541511",
    )
    ok, fit_class, fit_score, _ = business_fit(row)
    assert ok
    assert fit_class in {"SPM_WEB", "SPM_SOFTWARE_AUTOMATION", "SPM_IT_POTENTIAL"}
    assert fit_score >= 70


def test_unknown_sam_naics_does_not_block_strong_digital_title():
    row = rec(
        "SAM:WEIRD",
        "Web portal redesign and accessibility remediation",
        portal="US_SAM",
        naics="999999",
    )
    ok, fit_class, fit_score, _ = business_fit(row)
    assert ok
    assert fit_class == "SPM_WEB"
    assert fit_score >= 80
