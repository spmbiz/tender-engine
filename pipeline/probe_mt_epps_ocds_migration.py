from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from pipeline.discover_mt_epps_ocds import discover_manifest, fetch_package
except ModuleNotFoundError:
    from discover_mt_epps_ocds import discover_manifest, fetch_package

import requests

OUT = Path(os.getenv("MT_EPPS_MIGRATION_PROBE_OUT", "control/mt_epps_ocds_migration_probe.json"))
DEPLOYMENT = datetime(2023, 1, 16, tzinfo=timezone.utc)


def clean(value):
    return " ".join(str(value or "").split())


def pdt(value):
    s = clean(value)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/7.3 (+Malta ePPS OCDS migration continuity probe)", "Accept": "application/json,*/*"})
    errors = []
    selected_base = None
    manifest = []
    jan = None
    records = []
    try:
        selected_base, manifest, manifest_meta = discover_manifest(session)
        jan = next((x for x in manifest if x.get("month") == "2023-01"), None)
        if jan is None:
            raise RuntimeError("JANUARY_2023_PACKAGE_NOT_OFFERED")
        package = fetch_package(selected_base, jan)
        records = package.pop("records")
    except Exception as exc:
        manifest_meta = {}
        package = {}
        errors.append({"error": repr(exc)})

    migrated_active = []
    predeployment_compiled = []
    predeployment_tender_start = []
    for record in records:
        compiled = record.get("compiledRelease") if isinstance(record.get("compiledRelease"), dict) else {}
        ocid = clean(record.get("ocid") or compiled.get("ocid"))
        record_date = pdt(record.get("date"))
        compiled_date = pdt(compiled.get("date"))
        tender = compiled.get("tender") if isinstance(compiled.get("tender"), dict) else {}
        period = tender.get("tenderPeriod") if isinstance(tender.get("tenderPeriod"), dict) else {}
        start = pdt(period.get("startDate"))
        end = pdt(period.get("endDate"))
        status = clean(tender.get("status")).lower()
        title = clean(tender.get("title"))

        row = {
            "ocid": ocid or None,
            "record_date": record_date.isoformat() if record_date else None,
            "compiled_date": compiled_date.isoformat() if compiled_date else None,
            "tender_start": start.isoformat() if start else None,
            "tender_end": end.isoformat() if end else None,
            "tender_status": status or None,
            "title": title or None,
        }
        if compiled_date and compiled_date < DEPLOYMENT:
            predeployment_compiled.append(row)
        if start and start < DEPLOYMENT:
            predeployment_tender_start.append(row)
        if start and start < DEPLOYMENT and end and end >= DEPLOYMENT and status not in {"cancelled", "canceled", "complete", "withdrawn", "unsuccessful"}:
            migrated_active.append(row)

    payload = {
        "schema": "MALTA_EPPS_OCDS_MIGRATION_CONTINUITY_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deployment_boundary": DEPLOYMENT.isoformat(),
        "selected_official_base": selected_base,
        "manifest_first_month": manifest[0].get("month") if manifest else None,
        "manifest_last_month": manifest[-1].get("month") if manifest else None,
        "january_2023_offered": jan is not None,
        "january_2023_record_count": len(records),
        "predeployment_compiled_records": len(predeployment_compiled),
        "predeployment_tender_start_records": len(predeployment_tender_start),
        "active_across_deployment_records": len(migrated_active),
        "active_across_deployment_sample": migrated_active[:25],
        "predeployment_start_sample": predeployment_tender_start[:25],
        "errors": errors,
        "pass": bool(not errors and records and migrated_active),
        "semantics": (
            "Read-only continuity probe for the production Malta ePPS OCDS January 2023 record package. "
            "It tests whether the first production OCDS package contains tenders whose tender period began before the 16 January 2023 new-ePPS deployment and remained open across that boundary. "
            "A positive result demonstrates migration continuity for active legacy procedures; it does not by itself grant full live-universe coverage."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
