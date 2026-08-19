from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.publiccontractsscotland.gov.uk/v1/Notices"
NOW = datetime.now(timezone.utc)


def summarize(value, depth=0):
    if depth > 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {k: summarize(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return {"type": "list", "len": len(value), "sample": summarize(value[0], depth + 1) if value else None}
    return type(value).__name__


def collect_ocids(value, out):
    if isinstance(value, dict):
        ocid = value.get("ocid")
        if isinstance(ocid, str) and ocid:
            out.add(ocid)
        for v in value.values():
            collect_ocids(v, out)
    elif isinstance(value, list):
        for v in value:
            collect_ocids(v, out)


def main():
    month = NOW.strftime("%m-%Y")
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Tender-Engine/PCS-API-Probe", "Accept": "application/json"})
    results = []
    for notice_type in (2, 5, 21, 22, 23, 24, 102):
        item = {"notice_type": notice_type, "dateFrom": month}
        try:
            r = sess.get(BASE, params={"dateFrom": month, "noticeType": notice_type, "outputType": 0}, timeout=90)
            item["status"] = r.status_code
            item["bytes"] = len(r.content)
            if r.status_code < 400:
                data = r.json()
                ocids = set()
                collect_ocids(data, ocids)
                item["ocid_count"] = len(ocids)
                item["shape"] = summarize(data)
                item["sample_ocids"] = sorted(ocids)[:10]
            else:
                item["body_sample"] = r.text[:1000]
        except Exception as exc:
            item["error"] = repr(exc)
        results.append(item)
    payload = {
        "schema": "PCS_OFFICIAL_API_PROBE_V1",
        "generated_at": NOW.isoformat(),
        "base": BASE,
        "month": month,
        "results": results,
    }
    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_api_probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
