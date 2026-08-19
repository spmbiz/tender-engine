from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_za_uses_adaptive_official_ocds_windows_not_one_brittle_range():
    body = text("pipeline/discover_za_etenders_ocds_resilient.py")
    assert "ZA_ETENDERS_OCDS_ADAPTIVE_RELEASE_WINDOWS_V2" in body
    assert "BISECT" in body
    assert "REDUCE_PAGE_SIZE" in body
    assert "FAILED_SINGLE_DAY" in body
    assert "live_coverage_credit_allowed" in body
    wrapper = text("pipeline/discover_za_etenders_ocds.py")
    assert "discover_za_etenders_ocds_resilient" in wrapper


def test_pcs_has_open_contracting_month_type_api_collector_fail_closed():
    body = text("pipeline/discover_uk_pcs_api_current.py")
    assert "PCS_OFFICIAL_OCDS_MONTH_TYPE_V1_KINGFISHER_PATTERN" in body
    assert "open-contracting/kingfisher-collect" in body
    assert '"/Notices"' in body
    assert "noticeType" in body
    assert "outputType" in body
    assert '"live_coverage_credit_allowed": False' in body
    assert '"enumeration_complete": False' in body


def test_cyprus_recent_tenders_can_only_add_recall_never_full_coverage():
    body = text("pipeline/discover_epps_public.py")
    assert "latest=true&searchSelect=4" in body
    assert "CYPRUS_RECENT_TENDERS_QUICKSEARCH_RECALL_ONLY" in body
    assert 'SOURCE!="CYPRUS_EPPS"' in body
    assert "live_coverage_credit_allowed" in body
