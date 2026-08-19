from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import requests

OFFICIAL_RSS_URL = "https://www.tenders.gov.au/public_data/rss/rss.xml"
DEFAULT_DEPLOYMENT_CONTROL = Path("control/austender_bridge_deployment.json")


def load_bridge_url() -> tuple[str, str]:
    """Resolve bridge URL without inventing one.

    Environment always wins. Otherwise consume only a deployment record that was
    persisted by our own verified deploy workflow. The provenance string is
    carried into telemetry so downstream guards can distinguish both cases.
    """
    env_url = os.getenv("AUSTENDER_BRIDGE_URL", "").strip()
    if env_url:
        return env_url, "ENVIRONMENT"

    control_path = Path(os.getenv("AUSTENDER_BRIDGE_DEPLOYMENT_CONTROL", str(DEFAULT_DEPLOYMENT_CONTROL)))
    try:
        obj = json.loads(control_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return "", "UNCONFIGURED"
    if not isinstance(obj, dict):
        return "", "UNCONFIGURED"
    if obj.get("verified") is not True:
        return "", "CONTROL_UNVERIFIED"
    url = str(obj.get("deployment_url") or "").strip()
    if not url.startswith("https://"):
        return "", "CONTROL_INVALID_URL"
    return url, "VERIFIED_DEPLOYMENT_CONTROL"


def _header(response: requests.Response, name: str) -> str:
    return str(response.headers.get(name) or "").strip()


def fetch_verified_bridge(
    url: str,
    *,
    user_agent: str,
    timeout: int = 60,
    token: str | None = None,
    session: Any = requests,
) -> tuple[bytes | None, dict[str, Any], list[dict[str, Any]]]:
    """Fetch bridge bytes and validate the relay contract before accepting them."""
    telemetry: dict[str, Any] = {"bridge_url": url}
    warnings: list[dict[str, Any]] = []
    if not url:
        return None, telemetry, warnings

    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = session.get(url, timeout=timeout, headers=headers)
    except Exception as exc:
        warnings.append({"type": "BRIDGE_TRANSPORT_ERROR", "message": repr(exc)})
        return None, telemetry, warnings

    telemetry["bridge_http_status"] = response.status_code
    if response.status_code != 200:
        warnings.append({"type": "BRIDGE_HTTP_ERROR", "status": response.status_code})
        return None, telemetry, warnings

    claimed_upstream = _header(response, "X-Tender-Engine-Upstream")
    upstream_status = _header(response, "X-Tender-Engine-Upstream-Status")
    claimed_sha = _header(response, "X-Tender-Engine-SHA256").lower()
    body = bytes(response.content)
    actual_sha = hashlib.sha256(body).hexdigest()
    telemetry.update({
        "bridge_claimed_upstream": claimed_upstream,
        "bridge_claimed_upstream_status": upstream_status,
        "bridge_claimed_sha256": claimed_sha,
        "bridge_actual_sha256": actual_sha,
        "bridge_bytes": len(body),
    })

    failures = []
    if claimed_upstream != OFFICIAL_RSS_URL:
        failures.append({"type": "BRIDGE_UPSTREAM_IDENTITY_MISMATCH", "expected": OFFICIAL_RSS_URL, "actual": claimed_upstream})
    if upstream_status != "200":
        failures.append({"type": "BRIDGE_UPSTREAM_STATUS_NOT_200", "actual": upstream_status})
    if not claimed_sha or claimed_sha != actual_sha:
        failures.append({"type": "BRIDGE_SHA256_MISMATCH", "claimed": claimed_sha or None, "actual": actual_sha})
    if not body:
        failures.append({"type": "BRIDGE_EMPTY_BODY"})
    if failures:
        warnings.extend(failures)
        telemetry["bridge_contract_verified"] = False
        return None, telemetry, warnings

    telemetry["bridge_contract_verified"] = True
    telemetry["bridge_contract"] = "OWNED_CLOUDFLARE_RELAY_OFFICIAL_AUSTENDER_RSS_SHA256_VERIFIED"
    return body, telemetry, warnings


def harvest_verified_bridge(
    url: str,
    *,
    user_agent: str,
    records: dict,
    telemetry: dict,
    warnings: list,
    parse_callback: Callable[[bytes, dict, dict, list, str], bool],
    token: str | None = None,
) -> bool:
    body, bridge_telemetry, bridge_warnings = fetch_verified_bridge(
        url,
        user_agent=user_agent,
        token=token,
    )
    telemetry.update(bridge_telemetry)
    warnings.extend(bridge_warnings)
    if body is None:
        return False
    ok = parse_callback(body, records, telemetry, warnings, "VERIFIED_OFFICIAL_RSS_CLOUDFLARE_BRIDGE")
    if not ok:
        telemetry["bridge_contract_verified"] = False
    return ok
