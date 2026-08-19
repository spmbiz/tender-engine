from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.publiccontractsscotland.gov.uk/NoticeDownload/Download.aspx"
OUT = Path("control/pcs_bulk_sample.json")


def clean(v):
    return " ".join(str(v or "").split())


def label_map(form):
    out = {}
    for label in form.find_all("label"):
        target = label.get("for")
        if target:
            out[target] = clean(label.get_text(" ", strip=True))
    return out


def run_probe():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Tender-Engine/PCS-Bulk-Sample/2.0",
        "Accept": "text/html,application/json,application/octet-stream,*/*",
    })
    landing = s.get(URL, timeout=60)
    landing.raise_for_status()
    soup = BeautifulSoup(landing.text, "html.parser")
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if not form:
        raise RuntimeError("NO_FORM")

    labels = label_map(form)
    payload = {}
    for node in form.find_all("input"):
        name = node.get("name")
        typ = (node.get("type") or "").lower()
        if name and typ == "hidden":
            payload[name] = node.get("value") or ""

    select = form.find("select", attrs={"name": "ctl00$maincontent$ddDateRange"})
    if not select:
        raise RuntimeError("NO_DATE_RANGE")
    option = None
    for o in select.find_all("option"):
        if "August, 2026" in o.get_text(" ", strip=True):
            option = o
            break
    if option is None:
        option = select.find("option")
    if option is None:
        raise RuntimeError("NO_DATE_OPTION")

    selected = {
        "collection_type": "0",
        "date_range": option.get("value") or "",
        "output_type": "0",
        "download_type": "0",
        "notice_type": "102",
    }
    payload.update({
        "ctl00$maincontent$rblCollectionType": selected["collection_type"],
        "ctl00$maincontent$ddDateRange": selected["date_range"],
        "ctl00$maincontent$rblOutputType": selected["output_type"],
        "ctl00$maincontent$rblDownloadType": selected["download_type"],
        "ctl00$maincontent$rblNoticeTypes": selected["notice_type"],
        "ctl00$maincontent$buttonDownload": "Download",
    })

    # Useful when the site's radio value-to-label mapping changes.
    radio_debug = []
    for node in form.find_all("input", attrs={"type": "radio"}):
        radio_debug.append({
            "name": node.get("name"),
            "id": node.get("id"),
            "value": node.get("value"),
            "checked": node.has_attr("checked"),
            "label": labels.get(node.get("id")),
        })

    r = s.post(URL, data=payload, timeout=90, allow_redirects=True)
    ctype = r.headers.get("content-type") or ""
    result = {
        "schema": "PCS_BULK_SAMPLE_V2_ALWAYS_PERSIST",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "landing_status": landing.status_code,
        "post_status": r.status_code,
        "final_url": r.url,
        "selected": selected,
        "radio_debug": radio_debug,
        "content_type": ctype,
        "content_disposition": r.headers.get("content-disposition"),
        "bytes": len(r.content),
        "prefix_text": r.text[:1500] if any(x in ctype.lower() for x in ("text", "json", "xml", "html")) else None,
        "response_headers": {
            k: v for k, v in r.headers.items()
            if k.lower() in {"content-type", "content-disposition", "location", "content-length", "cache-control"}
        },
    }
    try:
        data = r.json()
        result["json_type"] = type(data).__name__
        if isinstance(data, dict):
            result["keys"] = list(data)[:30]
            rel = data.get("releases")
            result["release_count"] = len(rel) if isinstance(rel, list) else None
            if isinstance(rel, list) and rel:
                result["sample_ocids"] = [str(x.get("ocid") or "") for x in rel[:10] if isinstance(x, dict)]
    except Exception as exc:
        result["json_error"] = repr(exc)
    return result


def main():
    OUT.parent.mkdir(exist_ok=True)
    try:
        result = run_probe()
    except BaseException as exc:
        result = {
            "schema": "PCS_BULK_SAMPLE_V2_ALWAYS_PERSIST",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "probe_error": repr(exc),
            "traceback": traceback.format_exc()[-12000:],
        }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
