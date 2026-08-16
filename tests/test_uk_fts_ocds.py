from pipeline import discover_uk_fts_ocds as fts


def test_fts_follows_opaque_next_url_without_reconstructing_cursor(monkeypatch):
    calls = []
    pages = [
        (
            {"releases": [{"id": "r1"}], "links": {"next": "https://example.test/next?cursor=OPAQUE=="}},
            {"url": "https://example.test/first"},
        ),
        ({"releases": [{"id": "r2"}]}, {"url": "https://example.test/next?cursor=OPAQUE=="}),
    ]

    def fake_get_json(session, url, params=None, retries=7):
        calls.append((url, params))
        return pages[len(calls) - 1]

    monkeypatch.setattr(fts, "get_json", fake_get_json)
    rows, telemetry, errors = fts.harvest_stage(
        object(),
        stage="tender",
        updated_from="2026-08-15T00:00:00",
        updated_to="2026-08-16T00:00:00",
        page_limit=100,
        max_pages=5,
    )
    assert [r["id"] for r in rows] == ["r1", "r2"]
    assert calls[0][1]["stages"] == "tender"
    assert calls[1] == ("https://example.test/next?cursor=OPAQUE==", None)
    assert errors == []
    assert len(telemetry) == 2


def test_fts_records_page_cap_as_explicit_truncation(monkeypatch):
    def fake_get_json(session, url, params=None, retries=7):
        return {"releases": [{"id": "r1"}], "links": {"next": "https://example.test/more"}}, {"url": url}

    monkeypatch.setattr(fts, "get_json", fake_get_json)
    _, _, errors = fts.harvest_stage(
        object(),
        stage="award",
        updated_from="2026-08-15T00:00:00",
        updated_to="2026-08-16T00:00:00",
        page_limit=100,
        max_pages=1,
    )
    assert errors == [{"stage": "award", "error": "TRUNCATED_BY_PAGE_CAP", "max_pages": 1}]
