from __future__ import annotations

"""High-recall Estonia RHR discovery from official monthly open-data XML dumps.

Route learned from the hanke-radar OSS reference, but this implementation uses
only the official riigihanked.riik.ee bulk endpoint and preserves authoritative
notice/procedure identifiers. It intentionally applies no SPM category filter.
"""

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://riigihanked.riik.ee/rhr/api/public/v1"
BULK_BASE = f"{BASE}/opendata/notice"
UA = "Tender-Engine/4.0 (+public procurement research; official feeds only)"

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "efac": "http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1",
}
ACTIVE_SUBTYPES = {"2", "4", "7", "8", "9", "10", "11", "12", "13", "16", "17", "18", "19", "20"}
PARSEABLE = {"ContractNotice", "PriorInformationNotice"}


def text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_dt(date_value: str, time_value: str = "") -> datetime | None:
    if not date_value:
        return None
    try:
        date_part = date_value[:10]
        if time_value:
            time_part = time_value.split("+")[0].split("Z")[0].split(".")[0]
            tz_match = re.search(r"([+-]\d\d:\d\d|Z)$", date_value)
            tz = "+00:00" if not tz_match or tz_match.group(1) == "Z" else tz_match.group(1)
            return datetime.fromisoformat(f"{date_part}T{time_part}{tz}").astimezone(timezone.utc)
        return datetime.fromisoformat(date_value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(date_value[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            return None


def month_pairs(count: int, now: datetime) -> list[tuple[int, int]]:
    year, month = now.year, now.month
    out = []
    for _ in range(max(1, count)):
        out.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return out


def fetch_bytes(url: str, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/xml,*/*"})
            with urlopen(req, timeout=90) as response:
                return response.read()
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(12, 2**attempt))
    raise RuntimeError(f"RHR fetch failed for {url}: {last!r}")


def _first(root: ET.Element, path: str) -> ET.Element | None:
    return root.find(path, NS)


def parse_notice(notice: ET.Element, observed_at: str) -> dict | None:
    subtype = text(_first(notice, ".//efac:NoticeSubType/cbc:SubTypeCode"))
    if subtype not in ACTIVE_SUBTYPES:
        return None

    notice_id = text(_first(notice, './/cbc:ID[@schemeName="notice-id"]'))
    if not notice_id:
        return None
    procedure_id = text(_first(notice, ".//cbc:ContractFolderID"))
    title = text(_first(notice, ".//cac:ProcurementProject/cbc:Name"))
    description = text(_first(notice, ".//cac:ProcurementProject/cbc:Description"))
    procedure_type = text(_first(notice, ".//cbc:ProcedureCode"))

    cpvs: list[str] = []
    for el in notice.findall(".//cbc:ItemClassificationCode", NS):
        value = text(el)
        if value and value not in cpvs:
            cpvs.append(value)

    buyer = ""
    buyer_reg = ""
    company = _first(notice, ".//efac:Organization/efac:Company")
    if company is not None:
        buyer = text(company.find(".//cac:PartyName/cbc:Name", NS))
        buyer_reg = text(company.find(".//cac:PartyLegalEntity/cbc:CompanyID", NS))

    amount = _first(notice, ".//cbc:EstimatedOverallContractAmount")
    estimated_value = None
    currency = None
    if amount is not None:
        try:
            estimated_value = float(text(amount))
        except Exception:
            pass
        currency = amount.attrib.get("currencyID") or None

    deadline = None
    period = _first(notice, ".//cac:TenderSubmissionDeadlinePeriod")
    if period is not None:
        deadline = parse_dt(text(period.find("cbc:EndDate", NS)), text(period.find("cbc:EndTime", NS)))
    published = parse_dt(text(_first(notice, ".//cbc:IssueDate")))

    doc_landing = ""
    doc_uri = _first(notice, ".//cac:CallForTendersDocumentReference//cbc:URI")
    if doc_uri is not None:
        doc_landing = text(doc_uri)
    rhr_id = ""
    match = re.search(r"/procurement/(\d+)/", doc_landing)
    if match:
        rhr_id = match.group(1)
    notice_url = f"https://riigihanked.riik.ee/rhr-web/#/procurement/{rhr_id}/general-info" if rhr_id else None
    if not notice_url:
        notice_url = f"{BASE}/notice/{notice_id}/html"

    now = datetime.now(timezone.utc)
    return {
        "candidate_id": f"EE-RHR:{notice_id}",
        "source": "EE_RHR",
        "portal": "EE_RHR",
        "notice_id": notice_id,
        "procedure_id": procedure_id or None,
        "rhr_id": rhr_id or None,
        "title": title,
        "description": description,
        "buyer": buyer or None,
        "buyer_registration_id": buyer_reg or None,
        "country": "EE",
        "cpv": cpvs,
        "procurement_method": procedure_type or None,
        "notice_subtype": subtype,
        "estimated_value": estimated_value,
        "currency": currency,
        "published": published.isoformat() if published else None,
        "deadline": deadline.isoformat() if deadline else None,
        "current": deadline is None or deadline >= now,
        "notice_url": notice_url,
        "route": {
            "document_urls": [],
            "document_landing_url": doc_landing or None,
            "route_status": "RHR_DOCUMENT_ROUTE_DISCOVERED" if doc_landing else "UNKNOWN",
        },
        "observed_at": observed_at,
    }


def parse_bulk(xml_bytes: bytes, observed_at: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    rows = []
    for child in root:
        local = child.tag.split("}")[-1]
        if local not in PARSEABLE:
            continue
        rec = parse_notice(child, observed_at)
        if rec:
            rows.append(rec)
    return rows


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run(output: Path, months: int) -> dict:
    observed_at = datetime.now(timezone.utc).isoformat()
    records: dict[str, dict] = {}
    source_manifest = []
    errors = []
    for year, month in month_pairs(months, datetime.now(timezone.utc)):
        url = f"{BULK_BASE}/{year}/month/{month}/xml"
        try:
            payload = fetch_bytes(url)
            sha = hashlib.sha256(payload).hexdigest()
            parsed = parse_bulk(payload, observed_at)
            source_manifest.append({"year": year, "month": month, "url": url, "bytes": len(payload), "sha256": sha, "parsed_active_subtypes": len(parsed)})
            for rec in parsed:
                records[rec["candidate_id"]] = rec
        except Exception as exc:
            errors.append({"year": year, "month": month, "url": url, "error": repr(exc)})

    rows = sorted(records.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    current = [r for r in rows if r.get("current")]
    write_jsonl(output / "raw.jsonl", rows)
    write_jsonl(output / "current.jsonl", current)
    stats = {
        "source": "EE_RHR",
        "grain": "NOTICE_FIRST_TENDER",
        "months_requested": months,
        "raw_materialized": len(rows),
        "current_materialized": len(current),
        "generated_at": observed_at,
        "source_manifest": source_manifest,
        "errors": errors,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("discovery/global/ee_rhr"))
    ap.add_argument("--months", type=int, default=2)
    args = ap.parse_args()
    stats = run(args.output, max(1, args.months))
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["source_manifest"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
