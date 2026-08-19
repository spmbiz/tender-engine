from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.discover_es_placsp_atom_v2 import parse_xml_content, repair_xml_bytes


def test_strict_valid_xml_is_not_repaired():
    root, proof = parse_xml_content(b"<?xml version='1.0'?><feed><entry><title>A</title></entry></feed>")
    assert root.tag == "feed"
    assert proof == {"repair_applied": False}


def test_bare_ampersand_is_repaired_and_proven():
    payload = b"<?xml version='1.0'?><feed><entry><title>A & B</title></entry></feed>"
    root, proof = parse_xml_content(payload)
    assert root.find("./entry/title").text == "A & B"
    assert proof["repair_applied"] is True
    assert proof["bare_ampersands_escaped"] == 1
    assert proof["repaired_parse_ok"] is True
    assert proof["before_sha256"] != proof["after_sha256"]


def test_xml10_control_is_removed_and_proven():
    payload = b"<?xml version='1.0'?><feed><entry><title>A\x08B</title></entry></feed>"
    root, proof = parse_xml_content(payload)
    assert root.find("./entry/title").text == "AB"
    assert proof["invalid_xml10_controls_removed"] == 1


def test_named_and_numeric_entities_are_not_double_escaped():
    payload = b"<?xml version='1.0'?><feed><title>A &amp; B &#38; C</title></feed>"
    repaired, proof = repair_xml_bytes(payload)
    assert proof["bare_ampersands_escaped"] == 0
    root = ET.fromstring(repaired)
    assert root.find("./title").text == "A & B & C"
