from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_placsp_retries_strict_xml_instead_of_silently_recovering_corruption():
    body = text("pipeline/discover_es_placsp_atom.py")
    assert "PARSE_RETRIES" in body
    assert "ET.fromstring(r.content)" in body
    assert "except ET.ParseError" in body
    assert "Cache-Control" in body
    assert "PLACSP feed remained unreadable" in body
    assert "recover=" not in body
    assert "lxml" not in body


def test_placsp_keeps_official_feed_provenance_and_country():
    body = text("pipeline/discover_es_placsp_atom.py")
    assert "placsp_atom.HOSTED_FEED" in body
    assert "placsp_atom.AGGREGATED_FEED" in body
    assert "'atom_feed_url':start" in body
    assert "'feed_lane':kind" in body
    assert "'country':'ES'" in body
