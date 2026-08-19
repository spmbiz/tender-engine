from __future__ import annotations

"""South Africa eTenders OCDS compatibility entrypoint.

The National Treasury OCDS API intermittently returns 5xx responses on later
pages of broad date ranges. Production now uses the adaptive-window collector,
which recursively bisects release-date windows and reduces page size on a
single problematic day. It remains official-source-only and fails coverage
closed if any final day cannot be exhausted.
"""

import sys

from discover_za_etenders_ocds_resilient import main as resilient_main


def _drop_legacy_max_pages(argv: list[str]) -> list[str]:
    """Accept the former CLI contract while the global workflow migrates.

    `--max-pages` is deliberately ignored: the resilient collector's stopping
    proof is date-partition exhaustion, not an arbitrary page cap.
    """
    out = [argv[0]]
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--max-pages":
            i += 2
            continue
        if arg.startswith("--max-pages="):
            i += 1
            continue
        out.append(arg)
        i += 1
    return out


def main() -> None:
    sys.argv = _drop_legacy_max_pages(sys.argv)
    resilient_main()


if __name__ == "__main__":
    main()
