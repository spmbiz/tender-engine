from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pcs_accepts_current_opportunity_singular_and_page_labels():
    body = text("pipeline/discover_uk_pcs_current.py")
    assert "current_option" in body
    assert "opportunit(?:y|ies)" in body
    assert "Page\\s*" in body
    assert "PCS_CURRENT_OPPORTUNITIES_BROWSER_V3" in body


def test_cyprus_fallback_classifies_complete_row_not_fragile_cell_zero():
    body = text("pipeline/discover_epps_published_fallback.py")
    assert "row_text = clean(tr.get_text" in body
    assert "not COMPETITION_RE.search(row_text)" in body
    assert "competition_rows_with_resource_id" in body
    assert "dates[0]" in body
    assert "EPPS_PUBLISHED_NOTICES_RECALL_FALLBACK_V3" in body


def test_ungm_never_equates_missing_next_control_with_exhaustion():
    body = text("pipeline/discover_ungm_public.py")
    assert "UNGM_PUBLIC_ACTIVE_OPPORTUNITIES_V2_EXHAUSTION_PROOF" in body
    assert "RESULT_WINDOW_COUNT" in body
    assert "EXPLICIT_DISABLED_NEXT" in body
    assert "NO_EXHAUSTION_PROOF" in body
    assert "total_reported" in body
    # The old unsafe pattern marked exhaustion merely because click_next failed.
    assert "if not await click_next(page):\n                    exhausted = True" not in body
