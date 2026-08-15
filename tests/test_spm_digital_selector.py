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


def test_training_physical_staffing_and_hardware_do_not_enter_dce_queue():
    samples = [
        rec("R:1", "Digital skills training workshops for young people"),
        rec("R:2", "Construction works for a new building and web portal"),
        rec("R:3", "Robotic process automation staff augmentation services"),
        rec("R:4", "Supply of server hardware and network switches"),
        rec("R:5", "On-site equipment installation and maintenance services"),
    ]
    for row in samples:
        ok, fit_class, _, _ = business_fit(row)
        assert not ok, (row["title"], fit_class)


def test_generic_it_words_alone_do_not_qualify():
    row = rec("R:G", "Digital portal software application data maintenance services")
    ok, fit_class, score, _ = business_fit(row)
    assert not ok
    assert fit_class == "REJECT_NO_CORE_SIGNAL"
    assert score == -100


def test_portal_yield_can_never_rescue_noncore_candidate():
    row = rec("R:Y", "Digital skills training workshops", portal="EASY_PORTAL")
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
    row = rec("CPV:1", "Refonte du service numérique institutionnel", cpv="72413000")
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
    assert fit_class == "REJECT_SAM_NAICS_NONCORE"
    assert score == -100
    assert any("sam-naics" in r for r in reasons)


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
    assert fit_class in {"SPM_WEB", "SPM_SOFTWARE_AUTOMATION"}
    assert fit_score >= 70
