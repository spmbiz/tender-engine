from __future__ import annotations

"""Probe the current Lithuanian CVP IS public procurement API.

The Public Procurement Office (VPT) published this endpoint and a public API key
in its 2026-05-20 API instructions. The key is therefore not treated as a
private repository secret, but can be overridden with LT_CVP_API_KEY if VPT
rotates it.

This probe intentionally prints structure/field names instead of assuming a
schema. It is used to build a source-accurate production adapter.
"""

import json
import os
import sys
from typing import Any

import requests

ENDPOINT = "https://viesiejipirkimai.lt/epps-integration/api/cft-details-export"
PUBLIC_DOC_API_KEY = "acec29bd-687c-4609-b211-c01b6cf51b55"
UA = "Tender-Engine/5.6 (+public procurement research; Lithuanian VPT public API)"


def shape(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(k): shape(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "first": shape(value[0], depth + 1) if value else None,
        }
    if value is None:
        return None
    return type(value).__name__


def probe(page_size: int = 5, page_num: int = 1) -> tuple[dict[str, Any] | list[Any], dict[str, Any]]:
    key = os.getenv("LT_CVP_API_KEY", PUBLIC_DOC_API_KEY).strip()
    if not key:
        raise RuntimeError("LT_CVP_API_KEY is empty")
    response = requests.post(
        ENDPOINT,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/json",
            "apiKey": key,
            "User-Agent": UA,
        },
        json={"pageSize": page_size, "pageNum": page_num},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise RuntimeError(f"unexpected Lithuanian CVP response type: {type(payload).__name__}")
    meta = {
        "status_code": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "payload_shape": shape(payload),
    }
    return payload, meta


def main() -> None:
    payload, meta = probe()
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    # Print one public procurement record to make source mapping auditable. This
    # is public procurement data; no authentication/session data is emitted.
    sample = None
    if isinstance(payload, list) and payload:
        sample = payload[0]
    elif isinstance(payload, dict):
        for key in ("content", "items", "data", "results", "records", "cfts"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                sample = value[0]
                break
    print("LT_CVP_SAMPLE=" + json.dumps(sample, ensure_ascii=False, default=str)[:12000])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"LT_CVP_PROBE_ERROR={exc!r}", file=sys.stderr)
        raise
