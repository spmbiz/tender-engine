from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pcs_live_entrypoint_uses_official_bulk_ocds_not_browser_pagination():
    entry = text("pipeline/discover_uk_pcs_current.py")
    bulk = text("pipeline/discover_uk_pcs_bulk_current.py")
    assert "discover_uk_pcs_bulk_current" in entry
    assert "bulk_main" in entry
    assert "V13 direct ASP.NET" not in entry
    assert "NoticeDownload/Download.aspx" in bulk
    assert "PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_V1_KINGFISHER_PATTERN" in bulk
    assert "rblCollectionType" in bulk
    assert "rblOutputType" in bulk
    assert "rblDownloadType" in bulk
    assert "rblNoticeTypes" in bulk
    assert "open-contracting/kingfisher-collect" in bulk
    # Bulk rows are authoritative recall, but full current-universe coverage
    # stays fail-closed until an independent reconciliation exists.
    assert '"enumeration_complete":False' in bulk
    assert '"live_coverage_credit_allowed":False' in bulk


def test_cyprus_fallback_uses_row_text_but_never_mistakes_submission_for_deadline():
    body = text("pipeline/discover_epps_published_fallback.py")
    assert "row_text = clean(tr.get_text" in body
    assert "not COMPETITION_RE.search(row_text)" in body
    assert "competition_rows_with_resource_id" in body
    assert "published_notice_submission_date" in body
    assert "EPPS_CFT_WORKSPACE_FUTURE_DEADLINE" in body
    assert "Submission Date" in body
    assert "not the tender bid deadline" in body
    assert "EPPS_PUBLISHED_NOTICES_RECALL_FALLBACK_V4_WORKSPACE_DEADLINE" in body


def test_ungm_requires_empty_paged_search_proof_inside_browser_session():
    body = text("pipeline/discover_ungm_public.py")
    assert "UNGM_PUBLIC_BROWSER_SESSION_SEARCH_V4" in body
    assert 'SEARCH_PATH = "/Public/Notice/Search"' in body
    assert '"PageIndex": page_index' in body
    assert '"DeadlineFrom": NOW.strftime' in body
    assert "FIRST_EMPTY_SAME_ORIGIN_SEARCH_PAGE" in body
    assert "browser_search" in body
    assert "total_reported" in body
    assert "user_agent=UA" not in body
    # Missing/unknown browser UI pagination must never itself imply exhaustion.
    assert "click_next" not in body
