from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://www.eprocurement.gov.cy"
WORKSPACE = BASE + "/epps/cft/prepareViewCfTWS.do?resourceId={}"
UA = "Tender-Engine/7.5 (+official Cyprus ePPS public CfT workspace currentness resolver)"
NOW = datetime.now(timezone.utc)
CY_TZ = ZoneInfo("Europe/Nicosia")
RETRIES = max(1, min(8, int(os.getenv("CY_EPPS_WORKSPACE_RETRIES", "5"))))
DELAY = max(0.0, float(os.getenv("CY_EPPS_WORKSPACE_DELAY_SECONDS", "0.18")))

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\b")
DEADLINE_MARKERS = (
    "time-limit for receipt of tenders or requests to participate",
    "time limit for receipt of tenders or requests to participate",
    "deadline",
    "closing date",
    "submission deadline",
    "καταληκτική ημερομηνία υποβολής προσφορών",
    "καταληκτική ημερομηνία",
    "καταληκ",
)
TERMINAL_PATTERNS = (
    r"\bclosed\b",
    r"\bcompleted\b",
    r"\bcancelled\b",
    r"\bcanceled\b",
    r"\bterminated\b",
    r"\bexpired\b",
    r"\bawarded\b",
    r"κλειστ",
    r"ολοκληρω",
    r"ακυρ",
    r"λήξ",
    r"ανατέθ",
)
CAPTCHA_RE = re.compile(r"captcha|recaptcha", re.I)
LOGIN_RE = re.compile(r"\blog\s*in\b|σύνδεση", re.I)


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                yield value


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_local_dt(fragment: str) -> datetime | None:
    match = DATE_RE.search(clean(fragment))
    if not match:
        return None
    raw = match.group(1) + ((" " + match.group(2)) if match.group(2) else "")
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            local = datetime.strptime(raw, fmt).replace(tzinfo=CY_TZ)
            return local.astimezone(timezone.utc)
        except ValueError:
            pass
    return None


def deadline_from_text(text: str) -> tuple[datetime | None, str | None]:
    lower = text.lower()
    for marker in DEADLINE_MARKERS:
        pos = lower.find(marker.lower())
        if pos < 0:
            continue
        parsed = parse_local_dt(text[pos:pos + 900])
        if parsed:
            return parsed, marker
    return None, None


def terminal_evidence(text: str) -> list[str]:
    hits = []
    for pattern in TERMINAL_PATTERNS:
        if re.search(pattern, text, re.I):
            hits.append(pattern)
    return hits


def labelled_value(soup: BeautifulSoup, markers: tuple[str, ...]) -> str | None:
    marker_set = tuple(x.lower() for x in markers)
    for node in soup.find_all(["th", "td", "label", "dt", "span", "div"]):
        label = clean(node.get_text(" ", strip=True))
        lower = label.lower()
        if not any(marker in lower for marker in marker_set):
            continue
        sibling = node.find_next_sibling()
        if sibling:
            value = clean(sibling.get_text(" ", strip=True))
            if value and value != label:
                return value[:1000]
        parent = node.parent
        if parent:
            cells = parent.find_all(["td", "dd"], recursive=False)
            if len(cells) >= 2:
                value = clean(cells[-1].get_text(" ", strip=True))
                if value and value != label:
                    return value[:1000]
    return None


def fetch_workspace(session: requests.Session, resource_id: str) -> dict[str, Any]:
    url = WORKSPACE.format(resource_id)
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = session.get(url, timeout=60, allow_redirects=True)
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP_{response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            text = clean(soup.get_text(" ", strip=True))
            if CAPTCHA_RE.search(text):
                raise RuntimeError("CAPTCHA_PRESENT_ON_PUBLIC_WORKSPACE")
            deadline, marker = deadline_from_text(text)
            terminal = terminal_evidence(text)
            title = labelled_value(soup, ("cft title", "tender title", "τίτλος διαγωνισμού", "τίτλος"))
            buyer = labelled_value(soup, ("contracting authority", "contracting entity", "αναθέτουσα αρχή", "αναθέτων"))
            status = labelled_value(soup, ("cft status", "tender status", "κατάσταση διαγωνισμού", "κατάσταση"))
            return {
                "resource_id": resource_id,
                "workspace_url": response.url,
                "http_status": response.status_code,
                "deadline": deadline.isoformat() if deadline else None,
                "deadline_marker": marker,
                "terminal_evidence": terminal,
                "workspace_title": title,
                "workspace_buyer": buyer,
                "workspace_status": status,
                "login_text_seen": bool(LOGIN_RE.search(text)),
                "body_text_prefix": text[:6000],
            }
        except Exception as exc:
            last = exc
            if attempt + 1 < RETRIES:
                time.sleep(min(15.0, 1.25 * (2**attempt)))
    raise RuntimeError(f"CY_EPPS_WORKSPACE_FAILED resourceId={resource_id}: {last!r}")


def classify(meta: dict[str, Any], workspace: dict[str, Any]) -> dict[str, Any]:
    resource_id = clean(meta.get("resource_id"))
    deadline = None
    if workspace.get("deadline"):
        deadline = datetime.fromisoformat(str(workspace["deadline"]).replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        deadline = deadline.astimezone(timezone.utc)
    terminal = list(workspace.get("terminal_evidence") or [])
    if deadline is not None:
        current = deadline >= NOW and not terminal
        state = "CURRENT" if current else "NON_CURRENT"
        evidence = "CY_EPPS_PUBLIC_CFT_FUTURE_DEADLINE" if current else "CY_EPPS_PUBLIC_CFT_DEADLINE_EXPIRED_OR_TERMINAL"
    elif terminal:
        current = False
        state = "NON_CURRENT"
        evidence = "CY_EPPS_PUBLIC_CFT_EXPLICIT_TERMINAL_TEXT"
    else:
        current = False
        state = "UNKNOWN"
        evidence = "CY_EPPS_PUBLIC_CFT_NO_DEADLINE_OR_TERMINAL_EVIDENCE"

    return {
        "candidate_id": f"CY-EPPS:{resource_id}",
        "source": "CYPRUS_EPPS",
        "portal": "CYPRUS_EPPS",
        "grain": "NOTICE_FIRST_TENDER",
        "procedure_id": resource_id,
        "resource_id": resource_id,
        "notice_id": meta.get("notice_id"),
        "document_id": meta.get("document_id"),
        "title": workspace.get("workspace_title") or meta.get("title"),
        "buyer": workspace.get("workspace_buyer"),
        "country": "CY",
        "deadline": deadline.isoformat() if deadline else None,
        "current": current,
        "current_state": state,
        "currentness_evidence": evidence,
        "notice_url": meta.get("notice_url"),
        "workspace_url": workspace.get("workspace_url"),
        "workspace_status": workspace.get("workspace_status"),
        "terminal_evidence": terminal,
        "route": {
            "document_urls": [],
            "public_workspace_url": workspace.get("workspace_url"),
            "source_publication_count": meta.get("publication_count"),
        },
        "observed_at": NOW.isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--start-index", type=int, default=0)
    ap.add_argument("--end-index", type=int, default=-1)
    args = ap.parse_args()

    resources = list(iter_jsonl(args.input))
    start = max(0, args.start_index)
    end = len(resources) if args.end_index < 0 else min(len(resources), args.end_index)
    selected = resources[start:end]
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"})

    rows = []
    errors = []
    for idx, meta in enumerate(selected, start=start):
        resource_id = clean(meta.get("resource_id"))
        if not resource_id:
            errors.append({"index": idx, "type": "RESOURCE_ID_MISSING"})
            continue
        try:
            workspace = fetch_workspace(session, resource_id)
            row = classify(meta, workspace)
            rows.append(row)
        except Exception as exc:
            errors.append({"index": idx, "resource_id": resource_id, "error": repr(exc)})
        if DELAY:
            time.sleep(DELAY)

    current = [row for row in rows if row.get("current")]
    unknown = [row for row in rows if row.get("current_state") == "UNKNOWN"]
    non_current = [row for row in rows if row.get("current_state") == "NON_CURRENT"]
    transport_complete = bool(not errors and len(rows) == len(selected))
    currentness_complete = bool(transport_complete and not unknown)
    write_jsonl(out / "resolved.jsonl", rows)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "unknown.jsonl", unknown)
    stats = {
        "source": "CYPRUS_EPPS",
        "listing_contract": "CY_EPPS_PUBLIC_CFT_WORKSPACE_RESOLVER_V1",
        "input_total_resources": len(resources),
        "start_index": start,
        "end_index_exclusive": end,
        "resources_requested": len(selected),
        "resources_resolved": len(rows),
        "current_materialized": len(current),
        "non_current_materialized": len(non_current),
        "unknown_currentness": len(unknown),
        "transport_complete": transport_complete,
        "currentness_complete": currentness_complete,
        "enumeration_exhausted": transport_complete,
        "enumeration_complete": currentness_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": currentness_complete and bool(current),
        "errors": errors,
        "generated_at": NOW.isoformat(),
        "semantics": (
            "Public Cyprus ePPS CfT workspaces only. Every requested resourceId is fetched without authentication or CAPTCHA. "
            "Future explicit workspace deadline is sufficient for CURRENT; expired deadline or explicit terminal text is NON_CURRENT; a workspace lacking both deadline and terminal evidence is UNKNOWN and blocks live-coverage credit. "
            "Transport completeness and currentness completeness are reported separately so unresolved semantics can never be mistaken for exhaustive live coverage."
        ),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not transport_complete:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
