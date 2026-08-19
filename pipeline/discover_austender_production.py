from __future__ import annotations

"""Production AusTender entrypoint.

The legacy browser/RSS module remains the parser/fallback implementation. This
entrypoint changes only bridge acceptance semantics: a bridge is consumed only
through the verified Cloudflare relay contract (official upstream identity,
upstream HTTP 200, matching body SHA-256), and a URL persisted by our verified
deploy workflow is preferred over ad-hoc configuration.
"""

import asyncio
import os

from austender_bridge_transport import harvest_verified_bridge, load_bridge_url
from discover_austender_browser import (
    UA,
    harvest_browser,
    harvest_rss,
    parse_rss_content,
    persist,
)


async def main() -> None:
    records = {}
    telemetry = {
        "production_entrypoint": "AUSTENDER_PRODUCTION_VERIFIED_BRIDGE_V1",
    }
    errors = []
    warnings = []

    # Prefer the official endpoint directly whenever this runner can reach it.
    if harvest_rss(records, telemetry, warnings):
        telemetry["transport_selected"] = "OFFICIAL_CURRENT_ATM_RSS_DIRECT"
        persist(records, telemetry, errors, warnings)
        return

    bridge_url, provenance = load_bridge_url()
    telemetry["bridge_url_provenance"] = provenance
    trusted_env = os.getenv("AUSTENDER_BRIDGE_TRUSTED", "0").strip().lower() in {"1", "true", "yes"}
    bridge_allowed = provenance == "VERIFIED_DEPLOYMENT_CONTROL" or trusted_env
    if bridge_url and bridge_allowed:
        ok = harvest_verified_bridge(
            bridge_url,
            user_agent=UA,
            records=records,
            telemetry=telemetry,
            warnings=warnings,
            parse_callback=parse_rss_content,
            token=os.getenv("AUSTENDER_BRIDGE_TOKEN", "").strip() or None,
        )
        if ok:
            telemetry["transport_selected"] = "VERIFIED_OFFICIAL_RSS_CLOUDFLARE_BRIDGE"
            telemetry["bridge_trust_basis"] = (
                "VERIFIED_DEPLOYMENT_CONTROL_PLUS_RUNTIME_SHA256"
                if provenance == "VERIFIED_DEPLOYMENT_CONTROL"
                else "EXPLICIT_ENV_TRUST_PLUS_RUNTIME_SHA256"
            )
            persist(records, telemetry, errors, warnings)
            return
    elif bridge_url:
        warnings.append({
            "type": "BRIDGE_CONFIGURED_BUT_NOT_TRUSTED",
            "url": bridge_url,
            "provenance": provenance,
        })

    # GitHub-hosted runners are currently blocked by the official AusTender edge,
    # but retain the browser fallback so a future network-policy change is detected
    # automatically rather than hard-coding the block forever.
    await harvest_browser(records, telemetry, errors)
    telemetry.setdefault("transport_selected", "PUBLIC_BROWSER_FALLBACK")
    persist(records, telemetry, errors, warnings)


if __name__ == "__main__":
    asyncio.run(main())
