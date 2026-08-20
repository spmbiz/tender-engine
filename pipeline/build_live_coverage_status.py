from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CONTROL = Path("control")
OUT = CONTROL / "live_coverage_status.json"

SOURCES = {
    "TED_DEEP": ["ted_production_reconcile_proof.json", "ted_delta_production_proof.json"],
    "UK_PCS": ["pcs_full_reconcile_proof.json"],
    "IT_ANAC_PVL": ["it_anac_pvl_full_reconcile_proof.json"],
    "ES_PLACSP": ["es_placsp_live_proof.json"],
    "GR_KHMDHS": ["gr_khmdhs_live_proof.json"],
    "DE_DOE": ["de_doe_month_shards_proof.json", "de_doe_reconcile_proof.json"],
    "CY_EPPS_PUBLISHED": ["cy_global_published_full_proof.json", "cy_global_published_smoke_v2.json"],
    "CY_EPPS_CURRENT": ["cy_epps_full_current_proof.json", "cy_epps_workspace_contract_probe_v2.json"],
    "MT_EPPS_OCDS": ["mt_epps_ocds_reconcile_proof.json", "mt_epps_ocds_migration_probe.json"],
    "AU_AUSTENDER": ["austender_bridge_deployment.json", "austender_runner_probe.json"],
    "ROUTE_APPLY": ["apply_proven_live_routes_v2_status.json"],
}


def load(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def compact(obj: dict | None, path: Path):
    if not obj:
        return {"path": str(path), "present": False}
    keys = (
        "schema", "pass", "enumeration_complete", "enumeration_exhausted",
        "live_coverage_credit_allowed", "publication_window_enumeration_complete",
        "exact_registry_reconciliation", "exact_transport_reconciliation",
        "currentness_complete", "page_manifest_complete", "stable_official_totals",
        "months_requested", "months_completed", "windows_expected", "windows_completed",
        "total_pages_official", "total_pages_covered", "total_reported_official",
        "rows_materialized", "raw_materialized", "current_materialized",
        "unique_publication_ids", "unique_competition_resource_ids",
        "expected_resources", "resources_resolved", "unknown_currentness",
        "packages_requested", "packages_completed", "manifest_fresh_within_one_month",
        "adapter_exit_code", "errors", "routes_patched", "error",
    )
    out = {"path": str(path), "present": True}
    for key in keys:
        if key in obj:
            value = obj.get(key)
            if key == "errors" and isinstance(value, list):
                out[key] = value[:5]
                out["error_count"] = len(value)
            else:
                out[key] = value
    return out


def main():
    payload = {
        "schema": "TENDER_ENGINE_LIVE_COVERAGE_STATUS_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {},
    }
    for source, candidates in SOURCES.items():
        selected = None
        fallbacks = []
        for name in candidates:
            path = CONTROL / name
            obj = load(path)
            item = compact(obj, path)
            fallbacks.append(item)
            if obj is not None and selected is None:
                selected = item
        payload["sources"][source] = {
            "selected": selected or {"present": False},
            "candidates": fallbacks,
        }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
