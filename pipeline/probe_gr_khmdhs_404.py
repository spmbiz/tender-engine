from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv("GR_KHMDHS_404_PROBE_OUT", "control/gr_khmdhs_404_probe.json"))
URL = "https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice"
UA = "Tender-Engine/7.2 (+public procurement research; Greece KIMDIS empty-window contract probe)"

CASES = [
    ("known_nonempty_before", "2027-08-15 00:00", "2028-02-10 23:59"),
    ("suspected_empty", "2028-02-11 00:00", "2028-08-08 23:59"),
    ("known_nonempty_after", "2028-08-09 00:00", "2028-12-31 23:59"),
    ("far_future_control", "2099-01-01 00:00", "2099-06-29 23:59"),
]


def safe_json(response: requests.Response):
    try:
        return response.json()
    except Exception as exc:
        return {"_json_error": repr(exc), "_body_prefix": response.text[:4000]}


def main() -> None:
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
    })
    results = []
    for label, start, end in CASES:
        payload = {"finalDateFrom": start, "finalDateTo": end, "isModified": False}
        item = {"label": label, "payload": payload}
        try:
            response = session.post(URL, params={"page": 0}, json=payload, timeout=90)
            item.update({
                "status": response.status_code,
                "reason": response.reason,
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "retry_after": response.headers.get("retry-after"),
                "server": response.headers.get("server"),
                "body_bytes": len(response.content),
                "body_text_prefix": response.text[:4000],
                "json": safe_json(response),
            })
        except Exception as exc:
            item["error"] = repr(exc)
        results.append(item)

    suspected = next((x for x in results if x["label"] == "suspected_empty"), {})
    controls = [x for x in results if x["label"].startswith("known_nonempty")]
    payload = {
        "schema": "GR_KHMDHS_404_CONTRACT_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": URL,
        "results": results,
        "suspected_empty_status": suspected.get("status"),
        "known_nonempty_controls_ok": all(x.get("status") == 200 for x in controls),
        "pass": bool(suspected.get("status") == 404 and all(x.get("status") == 200 for x in controls)),
        "semantics": (
            "Read-only official KIMDIS Open Data probe comparing the exact future window that returned HTTP 404 with adjacent known-nonempty windows and a far-future control. "
            "The response body and selected headers are persisted verbatim enough to classify whether KIMDIS uses 404 as its documented empty-result contract. No 404 is promoted to empty by this probe itself."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
