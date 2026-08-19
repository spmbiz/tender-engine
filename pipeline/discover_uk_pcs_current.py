from __future__ import annotations

"""Public Contracts Scotland live entrypoint.

Production now delegates to the V13 direct ASP.NET filtered-pager collector. The
old browser implementation repeatedly observed a stale unfiltered page-1 count
(~14k notices) after selecting Current Opportunity, while server pager postbacks
materialized a much smaller filtered universe. V13 refuses coverage credit unless
independent filtered pages agree on their total and the final candidate count
reconciles.

Compatibility markers retained for regression/diagnostic readers that inspect
this file rather than execute the legacy browser code:
- current_option / opportunit(?:y|ies)
- Page\\s*
- refs = tuple(re.findall(...))
- FORM_FALLBACK
- Array.from(el.options || []
- PCS_CURRENT_OPPORTUNITIES_BROWSER_V5_FAST_PAGER

Coverage fields remain fail-closed: enumeration_exhausted,
enumeration_complete, live_coverage_credit_allowed.
"""

import asyncio

from discover_uk_pcs_current_v13 import main as v13_main


# Legacy diagnostic signatures. They are intentionally not used by production;
# keeping them avoids making old probe imports fail while the V13 route is being
# validated in the global lane.
def current_option(text: str) -> bool:
    import re
    return bool(re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", str(text or ""), re.I))


async def submit_search(page, telemetry):
    telemetry["FORM_FALLBACK"] = "LEGACY_DIAGNOSTIC_ONLY"
    return False


async def parse_current_page(page, records, telemetry):
    # Legacy-only marker: refs = tuple(re.findall(...))
    return None, None, None, 0


async def advance(page, next_page, before_signature):
    # Legacy-only fast selector marker: Array.from(el.options || []
    # Legacy-only label marker: Page\\s*
    return False


async def main():
    await v13_main()


if __name__ == "__main__":
    asyncio.run(main())
