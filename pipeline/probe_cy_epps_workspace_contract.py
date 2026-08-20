from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

try:
    from pipeline.discover_cy_epps_published_global import fetch as fetch_listing, page_url, parse_page
except ModuleNotFoundError:
    from discover_cy_epps_published_global import fetch as fetch_listing, page_url, parse_page

OUT = Path(os.getenv("CY_WORKSPACE_PROBE_OUT", "control/cy_epps_workspace_contract_probe.json"))
BASE = "https://www.eprocurement.gov.cy"
UA = "Tender-Engine/7.5 (+public procurement research; Cyprus public CfT workspace contract probe)"
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\b")
STATUS_PATTERNS = [
    re.compile(r"(?:CfT\s+Status|Tender\s+Status|Status|Κατάσταση(?:\s+Διαγωνισμού)?)\s*:?\s*([^|]{1,160})", re.I),
]
DEADLINE_MARKERS = (
    "time-limit for receipt of tenders or requests to participate",
    "time limit for receipt of tenders or requests to participate",
    "deadline",
    "closing date",
    "submission deadline",
    "καταληκτική ημερομηνία υποβολής προσφορών",
    "καταληκ",
)


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def parse_dt(text: str):
    text = clean(text)
    match = DATE_RE.search(text)
    if not match:
        return None
    raw = match.group(1) + ((" " + match.group(2)) if match.group(2) else "")
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def workspace(session: requests.Session, resource_id: str):
    url = f"{BASE}/epps/cft/prepareViewCfTWS.do?resourceId={resource_id}"
    last = None
    for attempt in range(4):
        try:
            response = session.get(url, timeout=60, allow_redirects=True)
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            text = clean(soup.get_text(" ", strip=True))
            lower = text.lower()
            deadline = None
            deadline_marker = None
            for marker in DEADLINE_MARKERS:
                pos = lower.find(marker.lower())
                if pos >= 0:
                    parsed = parse_dt(text[pos:pos + 700])
                    if parsed:
                        deadline = parsed
                        deadline_marker = marker
                        break
            statuses = []
            for pattern in STATUS_PATTERNS:
                for m in pattern.finditer(text):
                    value = clean(m.group(1))
                    if value and value not in statuses:
                        statuses.append(value[:200])
            terminal_hits = [
                term for term in (
                    "closed", "completed", "cancelled", "canceled", "terminated", "awarded", "expired",
                    "κλειστό", "ολοκληρω", "ακυρ", "λήξει", "ανατέθηκε",
                ) if term.lower() in lower
            ]
            return {
                "resource_id": resource_id,
                "url": response.url,
                "status": response.status_code,
                "title": clean(soup.title.get_text(" ", strip=True)) if soup.title else None,
                "deadline": deadline.isoformat() if deadline else None,
                "deadline_marker": deadline_marker,
                "status_matches": statuses[:20],
                "terminal_text_hits": terminal_hits,
                "text_prefix": text[:12000],
                "captcha_seen": "captcha" in lower,
                "login_seen": bool(re.search(r"\blog\s*in\b|σύνδεση", lower, re.I)),
            }
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(min(10, 1.5 * (2**attempt)))
    return {"resource_id": resource_id, "url": url, "error": repr(last)}


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"})
    errors = []
    listing_samples = []
    resources = []
    total_pages = None
    pager_prefix = None
    try:
        first_response = fetch_listing(session, page_url(1))
        first_rows, first_proof = parse_page(first_response, 1)
        total_pages = int(first_proof["total_pages"])
        pager_prefix = first_proof.get("pager_prefix")
        last_response = fetch_listing(session, page_url(total_pages, pager_prefix))
        last_rows, last_proof = parse_page(last_response, total_pages)
        for label, rows, proof in (("first", first_rows, first_proof), ("last", last_rows, last_proof)):
            listing_samples.append({
                "label": label,
                "proof": proof,
                "rows": rows,
            })
            for row in rows:
                rid = clean(row.get("resource_id"))
                if rid and rid not in resources:
                    resources.append(rid)
        resources = resources[:16]
    except Exception as exc:
        errors.append({"stage": "listing", "error": repr(exc)})

    workspaces = []
    for rid in resources:
        workspaces.append(workspace(session, rid))
        time.sleep(0.15)

    accessible = [x for x in workspaces if not x.get("error") and x.get("status") == 200]
    deadline_rows = [x for x in accessible if x.get("deadline")]
    terminal_rows = [x for x in accessible if x.get("terminal_text_hits") or x.get("status_matches")]
    captcha_rows = [x for x in accessible if x.get("captcha_seen")]
    payload = {
        "schema": "CY_EPPS_PUBLIC_CFT_WORKSPACE_CONTRACT_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": total_pages,
        "publisher_pager_prefix": pager_prefix,
        "resource_ids_probed": resources,
        "listing_samples": listing_samples,
        "workspaces": workspaces,
        "workspaces_accessible": len(accessible),
        "workspaces_with_deadline": len(deadline_rows),
        "workspaces_with_status_or_terminal_text": len(terminal_rows),
        "workspaces_with_captcha": len(captcha_rows),
        "errors": errors,
        "pass": bool(not errors and resources and len(accessible) == len(resources) and not captcha_rows),
        "semantics": (
            "Read-only probe of public Cyprus ePPS CfT workspaces for resourceIds sampled from the first and publisher-reported last national Published Notices pages. "
            "It records deadline/status evidence and verifies that workspace viewing itself is public and CAPTCHA-free. A passing probe establishes transport/access only; it does not claim all resourceIds can be classified current without a full reconciliation."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
