from __future__ import annotations

import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

import placsp_atom

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/ES_PLACSP"))
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc)
LOOKBACK = max(1, int(os.getenv("LOOKBACK_DAYS", "3")))
REQUEST_TIMEOUT = max(10, min(120, int(os.getenv("ES_REQUEST_TIMEOUT", "45"))))
PARSE_RETRIES = max(1, min(8, int(os.getenv("ES_PARSE_RETRIES", "4"))))
HARD_MAX_PAGES = max(0, int(os.getenv("ES_HARD_MAX_PAGES", "0")))
MAX_RUNTIME_SECONDS = max(60, int(os.getenv("ES_MAX_RUNTIME_SECONDS", "900")))
CUTOFF = NOW - timedelta(days=LOOKBACK)
FEEDS = [
    ("hosted", placsp_atom.HOSTED_FEED),
    ("aggregated", placsp_atom.AGGREGATED_FEED),
]
S = requests.Session()
S.headers.update({
    "User-Agent": "Tender-Engine/7.1 (+official Spain PLACSP Atom; recoverable-XML only)",
    "Accept": "application/atom+xml,application/xml,text/xml,*/*",
})

_BARE_AMP = re.compile(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z_:][A-Za-z0-9_.:-]*;)")
_INVALID_XML10 = re.compile(
    "[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]"
)


def clean(value):
    return " ".join(str(value or "").split())


def local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def pdt(value):
    if not value:
        return None
    s = clean(value)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def texts(root, name):
    return [clean(node.text) for node in root.iter() if local(node.tag) == name and clean(node.text)]


def first(root, *names):
    for name in names:
        values = texts(root, name)
        if values:
            return values[0]
    return None


def atom_child(entry, name):
    for node in list(entry):
        if local(node.tag) == name:
            return clean(node.text)
    return None


def find_links(entry):
    out = []
    for node in entry.iter():
        if local(node.tag) in ("URI", "URL") and clean(node.text):
            out.append(clean(node.text))
        href = node.attrib.get("href")
        if href:
            out.append(href)
    return list(dict.fromkeys(out))


def deadline_from(entry):
    values = []
    for name in (
        "EndDate",
        "EndDateTime",
        "TenderSubmissionDeadlinePeriod",
        "DeadlineDate",
        "ReceiptDeadlineDate",
        "SubmissionDueDate",
    ):
        values.extend(texts(entry, name))
    for value in values:
        parsed = pdt(value)
        if parsed:
            return parsed
    dates = texts(entry, "EndDate") + texts(entry, "DeadlineDate")
    times = texts(entry, "EndTime") + texts(entry, "DeadlineTime")
    if dates:
        return pdt(dates[0] + ("T" + times[0] if times else ""))
    return None


def repair_xml_bytes(content: bytes) -> tuple[bytes, dict]:
    before_sha = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8-sig", errors="replace")
    replacement_chars = text.count("\ufffd")
    repaired_controls, control_count = _INVALID_XML10.subn("", text)
    repaired, amp_count = _BARE_AMP.subn("&amp;", repaired_controls)
    payload = repaired.encode("utf-8")
    return payload, {
        "repair_applied": True,
        "bare_ampersands_escaped": amp_count,
        "invalid_xml10_controls_removed": control_count,
        "decode_replacement_chars": replacement_chars,
        "before_sha256": before_sha,
        "after_sha256": hashlib.sha256(payload).hexdigest(),
        "bytes_before": len(content),
        "bytes_after": len(payload),
    }


def parse_xml_content(content: bytes) -> tuple[ET.Element, dict]:
    try:
        return ET.fromstring(content), {"repair_applied": False}
    except ET.ParseError as strict_error:
        repaired, proof = repair_xml_bytes(content)
        proof["strict_parse_error"] = repr(strict_error)
        # Recovery is allowed only when the repaired payload is itself valid XML.
        root = ET.fromstring(repaired)
        proof["repaired_parse_ok"] = True
        if not any((proof.get(k) or 0) for k in (
            "bare_ampersands_escaped",
            "invalid_xml10_controls_removed",
            "decode_replacement_chars",
        )):
            raise RuntimeError(
                "PLACSP strict XML failed but deterministic repair changed no recognized invalid token"
            ) from strict_error
        return root, proof


def fetch_xml(url, page_no, telemetry):
    last = None
    for attempt in range(1, PARSE_RETRIES + 1):
        try:
            response = S.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={"Cache-Control": "no-cache" if attempt > 1 else "max-age=0"},
            )
            item = {
                "page": page_no,
                "url": url,
                "status": response.status_code,
                "bytes": len(response.content),
                "attempt": attempt,
                "content_type": response.headers.get("content-type"),
            }
            response.raise_for_status()
            root, repair = parse_xml_content(response.content)
            item.update(repair)
            item["parse_ok"] = True
            telemetry.append(item)
            return root
        except Exception as exc:
            telemetry.append({
                "page": page_no,
                "url": url,
                "attempt": attempt,
                "error": repr(exc),
            })
            last = exc
            if attempt < PARSE_RETRIES:
                time.sleep(min(8.0, attempt * 1.5))
    raise RuntimeError(f"PLACSP feed remained unreadable after {PARSE_RETRIES} attempts: {last!r}")


def parse_entry(kind, feed_start, entry):
    updated = pdt(atom_child(entry, "updated") or atom_child(entry, "published"))
    atom_id = atom_child(entry, "id")
    atom_title = atom_child(entry, "title")
    folder = first(entry, "ContractFolderID", "ContractFolderStatusCode", "ID")
    project_title = first(entry, "Name", "Title") or atom_title
    description = first(entry, "Description") or ""
    buyer = first(entry, "PartyName", "CorporateRegistrationSchemeName")
    amount = first(entry, "EstimatedOverallContractAmount", "TotalAmount", "TaxExclusiveAmount")
    currency = None
    for node in entry.iter():
        if local(node.tag) in ("EstimatedOverallContractAmount", "TotalAmount", "TaxExclusiveAmount") and clean(node.text):
            currency = node.attrib.get("currencyID") or node.attrib.get("currency")
            break
    deadline = deadline_from(entry)
    links = find_links(entry)
    detail = next(
        (u for u in links if "contrataciondelestado" in u and ("detalle" in u.lower() or "poc" in u.lower())),
        links[0] if links else None,
    )
    rid = clean(atom_id or folder)
    if not rid and not project_title:
        return None, updated
    cid = placsp_atom.candidate_id(entry) if rid else "ES-PLACSP:" + hashlib.sha256(
        f"{project_title}|{buyer}|{updated}".encode("utf-8")
    ).hexdigest()[:24]
    document_urls = placsp_atom.document_urls(entry, feed_start)
    current = True if deadline is None else deadline >= NOW
    return {
        "candidate_id": cid,
        "source": "ES_PLACSP",
        "portal": "ES_PLACSP",
        "notice_id": clean(folder or atom_id),
        "title": clean(project_title),
        "buyer": clean(buyer) or None,
        "country": "ES",
        "deadline": deadline.isoformat() if deadline else None,
        "published": updated.isoformat() if updated else None,
        "current": current,
        "currentness_evidence": (
            "PLACSP_FUTURE_DEADLINE" if deadline and deadline >= NOW
            else "PLACSP_NO_PARSEABLE_DEADLINE_RECALL" if deadline is None
            else "PLACSP_DEADLINE_EXPIRED"
        ),
        "notice_url": detail,
        "estimated_value": amount,
        "currency": currency,
        "description": clean(description),
        "route": {
            "document_urls": document_urls,
            "atom_id": clean(atom_id) or None,
            "contract_folder_id": clean(folder) or None,
            "atom_feed_url": feed_start,
            "feed_lane": kind,
        },
        "feed_lane": kind,
        "discovered_at": NOW.isoformat(),
    }, updated


def parse_feed(kind, start):
    url = start
    page_no = 0
    records = []
    telemetry = []
    seen = set()
    started = time.monotonic()
    stop_reason = None

    while url and url not in seen:
        if HARD_MAX_PAGES and page_no >= HARD_MAX_PAGES:
            stop_reason = "HARD_PAGE_CAP"
            break
        if time.monotonic() - started >= MAX_RUNTIME_SECONDS:
            stop_reason = "RUNTIME_BUDGET"
            break
        seen.add(url)
        page_no += 1
        root = fetch_xml(url, page_no, telemetry)
        entries = [node for node in root if local(node.tag) == "entry"]
        oldest = None
        for entry in entries:
            row, updated = parse_entry(kind, start, entry)
            if updated and (oldest is None or updated < oldest):
                oldest = updated
            if row:
                records.append(row)

        next_href = None
        for node in root.iter():
            if local(node.tag) == "link" and node.attrib.get("rel") == "next":
                next_href = node.attrib.get("href")
                break

        if oldest and oldest < CUTOFF:
            stop_reason = "PUBLICATION_CUTOFF_REACHED"
            break
        if not next_href:
            stop_reason = "NO_NEXT_LINK"
            url = None
            break
        url = urljoin(url, next_href)

    if url in seen and stop_reason is None:
        stop_reason = "REPEATED_NEXT_LINK"

    complete = stop_reason in {"PUBLICATION_CUTOFF_REACHED", "NO_NEXT_LINK"}
    return records, telemetry, {
        "feed": kind,
        "pages_fetched": page_no,
        "stop_reason": stop_reason,
        "publication_window_complete": complete,
        "hard_page_cap": HARD_MAX_PAGES or None,
        "runtime_seconds": round(time.monotonic() - started, 3),
    }


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    merged = {}
    telemetry = {}
    lane_proofs = {}
    errors = []

    for kind, url in FEEDS:
        try:
            rows, lane_telemetry, proof = parse_feed(kind, url)
            telemetry[kind] = lane_telemetry
            lane_proofs[kind] = proof
        except Exception as exc:
            telemetry[kind] = [{"error": repr(exc), "url": url}]
            lane_proofs[kind] = {
                "feed": kind,
                "publication_window_complete": False,
                "stop_reason": "ERROR",
            }
            errors.append({"feed": kind, "error": repr(exc)})
            continue
        for row in rows:
            old = merged.get(row["candidate_id"])
            if not old or str(row.get("published") or "") >= str(old.get("published") or ""):
                merged[row["candidate_id"]] = row

    rows = list(merged.values())
    current = [row for row in rows if row.get("current", True)]
    write_jsonl(OUT / "raw.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)

    publication_window_complete = bool(
        not errors
        and lane_proofs
        and all(proof.get("publication_window_complete") is True for proof in lane_proofs.values())
    )
    repaired_pages = sum(
        1 for items in telemetry.values() for item in items
        if isinstance(item, dict) and item.get("repair_applied")
    )
    stats = {
        "source": "ES_PLACSP",
        "listing_contract": "ES_PLACSP_OFFICIAL_ATOM_V2_RECOVERABLE_XML_EXHAUSTION",
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "with_direct_document_urls": sum(1 for row in rows if (row.get("route") or {}).get("document_urls")),
        "direct_document_url_count": sum(len((row.get("route") or {}).get("document_urls") or []) for row in rows),
        "lookback_days": LOOKBACK,
        "repaired_pages": repaired_pages,
        "publication_window_enumeration_complete": publication_window_complete,
        "enumeration_exhausted": publication_window_complete,
        "enumeration_complete": publication_window_complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": publication_window_complete and bool(current),
        "truncated_by_page_cap": any(p.get("stop_reason") == "HARD_PAGE_CAP" for p in lane_proofs.values()),
        "truncated_by_runtime_budget": any(p.get("stop_reason") == "RUNTIME_BUDGET" for p in lane_proofs.values()),
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "official_feeds": [item[1] for item in FEEDS],
        "lane_proofs": lane_proofs,
        "telemetry": telemetry,
        "semantics": (
            "Official PLACSP hosted and aggregated Atom feeds only. Strict XML parsing is attempted first. "
            "Recovery may only remove XML-1.0-invalid control characters, replace decoder U+FFFD evidence, or escape syntactically bare ampersands; every repaired page records hashes and counts. "
            "The requested publication window receives exhaustion credit only when each official feed reaches the requested date cutoff or naturally has no next link. Hard page caps, runtime budgets, repeated links, or parse errors remain fail-closed."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if not rows or not publication_window_complete:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
