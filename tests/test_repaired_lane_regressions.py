from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pcs_accepts_current_opportunity_and_uses_fast_page_selector():
    body = text("pipeline/discover_uk_pcs_current.py")
    assert "current_option" in body
    assert "opportunit(?:y|ies)" in body
    assert "Page\\s*" in body
    assert "refs = tuple(re.findall" in body
    assert "FORM_FALLBACK" in body
    assert "Array.from(el.options || []" in body
    assert "after != before_signature" not in body
    assert (
        "PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER" in body
        or "PCS_CURRENT_OPPORTUNITIES_BROWSER_V6_ASPNET_POSTBACK" in body
        or "PCS_CURRENT_OPPORTUNITIES_BROWSER_V7_NAVIGATION_SAFE_POSTBACK" in body
    )
    advance = body.split("async def advance(page, next_page, before_signature):", 1)[1].split("\n\nasync def main", 1)[0]
    if "PCS_CURRENT_OPPORTUNITIES_BROWSER_V6_ASPNET_POSTBACK" in body:
        assert "window.__doPostBack" in advance
        assert "form.submit()" not in advance
    if "PCS_CURRENT_OPPORTUNITIES_BROWSER_V7_NAVIGATION_SAFE_POSTBACK" in body:
        assert "page.expect_navigation" in advance
        assert "window.__doPostBack" in advance
        assert "setTimeout(() => window.__doPostBack" not in advance
        assert "form.submit()" not in advance


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
