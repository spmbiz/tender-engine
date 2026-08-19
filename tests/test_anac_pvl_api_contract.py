from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_anac_live_lane_uses_official_json_api_not_spa_cards():
    body = text("pipeline/discover_it_anac_pvl.py")
    assert 'API_URL = BASE + "/api/v0/avvisi"' in body
    assert '"dataPubblicazioneStart"' in body
    assert '"dataPubblicazioneEnd"' in body
    assert '"codiceScheda": QUERY_CODES' in body
    assert 'payload.get("content")' in body
    assert 'item.get("idAvviso")' in body
    assert 'item.get("dataScadenza")' in body
    assert 'documenti_di_gara_link' in body
    assert 'link_eform_ted' in body
    assert "async_playwright" not in body
    assert "a[href*='/bandi/']" not in body


def test_anac_api_lane_is_high_recall_but_fail_closed_on_world_coverage():
    body = text("pipeline/discover_it_anac_pvl.py")
    assert 'ANAC_PVL_OFFICIAL_AVVISI_API_V3' in body
    assert '"enumeration_complete": False' in body
    assert '"live_coverage_credit_allowed": False' in body
    assert 'ANAC_PVL_BANDI_PUBLICATION_WINDOW_RECALL_ONLY' in body
    assert 'ANAC_PVL_API_RECENT_BANDO_DEADLINE_UNKNOWN' in body
