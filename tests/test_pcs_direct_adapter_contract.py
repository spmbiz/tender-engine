from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pcs_direct_adapter_uses_official_webforms_state_and_filter():
    body = text("pipeline/discover_uk_pcs_current_direct.py")
    assert 'PAGE_TARGET = "ctl00$maincontent$PagingHelperTop$ddPageSelect"' in body
    assert 'NOTICE_TYPE = "ctl00$maincontent$ddDocType"' in body
    assert 'SEARCH_TARGET = "ctl00$maincontent$btnSearch"' in body
    assert 'Current Opportunity' in body
    assert 'context.request.post' in body
    assert '__VIEWSTATE' in body
    assert '__EVENTVALIDATION' in body
    assert 'PCS_CURRENT_OPPORTUNITIES_DIRECT_ASPNET_POST_V12' in body


def test_pcs_direct_adapter_reconciles_every_filtered_page_and_total():
    body = text("pipeline/discover_uk_pcs_current_direct.py")
    assert 'count_matches_official_total' in body
    assert 'source_rows_seen >= total_reported' in body
    assert 'len(rows) >= total_reported' in body
    assert 'page_no != wanted or tp2 != total_pages or tr2 != total_reported' in body
    assert 'filtered_current_search_proven' in body
    assert 'direct_filtered_post_proven' in body
    assert 'live_coverage_credit_allowed' in body


def test_pcs_date_only_deadline_is_end_of_day_uk_not_midnight():
    body = text("pipeline/discover_uk_pcs_current_direct.py")
    assert 'PCS_TZ = ZoneInfo("Europe/London")' in body
    assert 'hour=23, minute=59, second=59' in body
