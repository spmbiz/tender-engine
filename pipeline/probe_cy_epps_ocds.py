from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("CY_EPPS_OCDS_PROBE_OUT", "control/cy_epps_ocds_probe.json"))
PATHS = [
    "/ocds/services/recordpackage/getrecordpackagelist",
    "/epps/ocds/services/recordpackage/getrecordpackagelist",
]
BASES = [
    "https://www.eprocurement.gov.cy",
    "https://eprocurement.gov.cy",
    "http://www.eprocurement.gov.cy",
]
UA = "Tender-Engine/7.3 (+public procurement research; Cyprus ePPS public OCDS endpoint probe)"


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json,*/*"})
    results = []
    successes = []
    for base in BASES:
        for path in PATHS:
            url = base + path
            item = {"url": url}
            try:
                response = session.get(url, timeout=45, allow_redirects=True)
                item.update({
                    "status": response.status_code,
                    "final_url": response.url,
                    "content_type": response.headers.get("content-type"),
                    "bytes": len(response.content),
                })
                try:
                    payload = response.json()
                    item["json_type"] = type(payload).__name__
                    if isinstance(payload, dict):
                        item["json_keys"] = sorted(payload.keys())
                        packages = payload.get("packagesPerMonth")
                        if isinstance(packages, list):
                            item["packages_count"] = len(packages)
                            item["packages_first"] = packages[0] if packages else None
                            item["packages_last"] = packages[-1] if packages else None
                            if response.status_code == 200 and packages:
                                successes.append(item)
                except Exception as exc:
                    item["json_error"] = repr(exc)
                    item["body_prefix"] = response.text[:1000]
            except Exception as exc:
                item["error"] = repr(exc)
            results.append(item)

    payload = {
        "schema": "CY_EPPS_OCDS_RECORD_PACKAGE_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "successes": successes,
        "pass": bool(successes),
        "semantics": (
            "Read-only probe of official Cyprus eProcurement government hosts for the public European Dynamics OCDS record-package service used by compatible ePPS deployments. "
            "No CAPTCHA interaction, authentication, form submission, or tender action is performed."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not successes:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
