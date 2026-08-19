from __future__ import annotations

"""Public Contracts Scotland live entrypoint.

Primary collection is the official PCS Notice Download surface on the main
publiccontractsscotland.gov.uk domain. It returns genuine OCDS release packages
by calendar month and notice type, matching the maintained Open Contracting
Scotland collection pattern.

Production contract:

- DELTA: retain the fast/high-recall official monthly bulk reconstruction. It is
  useful live data but deliberately receives no full current-universe credit.
- RECONCILE: run the same bulk first, then independently enumerate the official
  Current Opportunity registry with the state-chained ASP.NET V13 adapter and
  exact-reconcile both official surfaces. Full coverage credit is granted only
  when both enumeration contracts are complete and every official current row
  exact-matches the bulk by OCID or exact notice reference.

This keeps PCS fail-closed while preserving useful bulk data even when the
independent current-registry reconciler is temporarily unavailable.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from discover_uk_pcs_bulk_current import main as bulk_main
from reconcile_uk_pcs_bulk_direct import reconcile


# Diagnostic compatibility marker retained for older tests/readers.
def current_option(text: str) -> bool:
    import re
    return bool(re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", str(text or ""), re.I))


def main() -> None:
    # Always materialize the authoritative official bulk first. If later
    # reconciliation fails, these rows remain durable and coverage stays closed.
    bulk_main()

    if os.getenv("DISCOVERY_MODE", "").strip().lower() != "reconcile":
        return

    bulk_out = Path(os.getenv("DISCOVERY_OUT", "discovery/global/UK_PCS_OCDS"))
    direct_out = bulk_out.parent / f"{bulk_out.name}-direct-reconcile"
    direct_out.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DISCOVERY_OUT"] = str(direct_out)
    env.pop("PCS_DIRECT_HARD_MAX_PAGES", None)
    script = Path(__file__).with_name("discover_uk_pcs_current_direct_v13.py")
    log_dir = bulk_out / "reconciliation"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "direct_runner.log"

    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(script.parent.parent),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )

    # The reconciler is intentionally able to consume an incomplete direct pack:
    # it preserves any authoritative direct-only current rows, but cannot grant
    # coverage credit unless the direct adapter itself proved exhaustion/counts.
    proof = reconcile(bulk_out, direct_out)
    orchestrator = {
        "schema": "PCS_CURRENT_RECONCILE_ORCHESTRATOR_V1",
        "direct_adapter_exit_code": proc.returncode,
        "direct_output": str(direct_out),
        "coverage_complete": proof.get("coverage_complete"),
        "direct_official_total_reported": proof.get("direct_official_total_reported"),
        "exact_matched_direct_rows": proof.get("exact_matched_direct_rows"),
        "direct_missing_from_bulk": proof.get("direct_missing_from_bulk"),
    }
    (log_dir / "orchestrator.json").write_text(
        json.dumps(orchestrator, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if proc.returncode != 0 or proof.get("coverage_complete") is not True:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
