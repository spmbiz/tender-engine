from __future__ import annotations

"""Public Contracts Scotland live entrypoint.

Primary collection is now the official PCS Notice Download surface on the main
publiccontractsscotland.gov.uk domain. It returns genuine OCDS release packages
by calendar month and notice type, matching the collection dimensions used by
Open Contracting Partnership's maintained Kingfisher Scotland spider while
avoiding both:

- the brittle/stale ASP.NET Current Opportunity pager; and
- the PCS API subdomain's incomplete TLS certificate chain.

The bulk collector remains fail-closed for *full current-registry coverage* until
its reconstructed active set is independently reconciled against the portal's
Current Opportunity universe. It is nevertheless authoritative high-recall live
data because every row comes from the official PCS OCDS publication surface.
"""

from discover_uk_pcs_bulk_current import main as bulk_main


# Diagnostic compatibility marker retained for older tests/readers.
def current_option(text: str) -> bool:
    import re
    return bool(re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", str(text or ""), re.I))


def main() -> None:
    bulk_main()


if __name__ == "__main__":
    main()
