from __future__ import annotations

"""Public Contracts Scotland live entrypoint.

Two official PCS surfaces are intentionally combined:

- the monthly OCDS Notice Download surface is retained as rich publication and
  procedure-level enrichment/provenance; and
- the state-chained ASP.NET Current Opportunity registry is authoritative for the
  live current-universe in reconcile mode because it is the actual filtered live
  listing and can prove stable page/count exhaustion.

DELTA remains the fast monthly bulk lane and receives no full current-universe
credit. RECONCILE enumerates the official Current Opportunity registry with V13,
then projects current.jsonl from that exhaustive registry while preserving bulk
rows and linkage evidence separately. Bulk enrichment recall is measured but is
not allowed to erase an opportunity that exists in the official current registry.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from discover_uk_pcs_bulk_current import main as bulk_main
from reconcile_uk_pcs_registry_authoritative import reconcile


# Diagnostic compatibility marker retained for older tests/readers.
def current_option(text: str) -> bool:
    import re
    return bool(re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", str(text or ""), re.I))


def main() -> None:
    # Materialize the official OCDS bulk first. It remains durable source evidence
    # and enrichment even if direct-registry enumeration later fails.
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

    proof = reconcile(bulk_out, direct_out)
    orchestrator = {
        "schema": "PCS_CURRENT_RECONCILE_ORCHESTRATOR_V2_REGISTRY_AUTHORITATIVE",
        "direct_adapter_exit_code": proc.returncode,
        "direct_output": str(direct_out),
        "coverage_complete": proof.get("coverage_complete"),
        "direct_official_total_reported": proof.get("direct_official_total_reported"),
        "direct_current_rows": proof.get("direct_current_rows"),
        "final_current_rows": proof.get("final_current_rows"),
        "exact_notice_reference_links": proof.get("exact_notice_reference_links"),
        "procedure_ocid_links": proof.get("procedure_ocid_links"),
        "direct_without_bulk_enrichment": proof.get("direct_without_bulk_enrichment"),
        "bulk_enrichment_recall_against_official_current": proof.get("bulk_enrichment_recall_against_official_current"),
        "bulk_current_not_in_direct_registry": proof.get("bulk_current_not_in_direct_registry"),
    }
    (log_dir / "orchestrator.json").write_text(
        json.dumps(orchestrator, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if proc.returncode != 0 or proof.get("coverage_complete") is not True:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
