from __future__ import annotations

import hashlib

from pipeline.austender_bridge_transport import OFFICIAL_RSS_URL, fetch_verified_bridge


class Response:
    def __init__(self, body: bytes, *, upstream=OFFICIAL_RSS_URL, status="200", sha=None, http=200):
        self.content = body
        self.status_code = http
        self.headers = {
            "X-Tender-Engine-Upstream": upstream,
            "X-Tender-Engine-Upstream-Status": status,
            "X-Tender-Engine-SHA256": sha if sha is not None else hashlib.sha256(body).hexdigest(),
        }


class Session:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


def test_verified_bridge_accepts_exact_official_identity_and_sha():
    body = b'<?xml version="1.0"?><rss><channel><item><title>x</title></item></channel></rss>'
    got, telemetry, warnings = fetch_verified_bridge(
        "https://bridge.example/rss.xml",
        user_agent="test",
        session=Session(Response(body)),
    )
    assert got == body
    assert warnings == []
    assert telemetry["bridge_contract_verified"] is True


def test_verified_bridge_rejects_wrong_upstream_even_with_valid_sha():
    body = b"<rss/>"
    got, telemetry, warnings = fetch_verified_bridge(
        "https://bridge.example/rss.xml",
        user_agent="test",
        session=Session(Response(body, upstream="https://evil.example/rss.xml")),
    )
    assert got is None
    assert telemetry["bridge_contract_verified"] is False
    assert any(x["type"] == "BRIDGE_UPSTREAM_IDENTITY_MISMATCH" for x in warnings)


def test_verified_bridge_rejects_body_hash_mismatch():
    body = b"<rss/>"
    got, telemetry, warnings = fetch_verified_bridge(
        "https://bridge.example/rss.xml",
        user_agent="test",
        session=Session(Response(body, sha="0" * 64)),
    )
    assert got is None
    assert telemetry["bridge_contract_verified"] is False
    assert any(x["type"] == "BRIDGE_SHA256_MISMATCH" for x in warnings)
