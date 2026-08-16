from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE = "https://search.worldbank.org/api/v2/procnotices"
DETAIL = "https://projects.worldbank.org/en/projects-operations/procurement-detail/"
UA = "Tender-Engine/5.5 (+public procurement research; World Bank public API)"
LIST_FIELDS = ",".join([
    "id", "notice_type", "notice_status", "noticedate", "submission_deadline_date", "submission_deadline_time",
    "project_ctry_name", "project_id", "project_name", "bid_reference_no", "bid_description", "procurement_group",
    "procurement_method_code", "procurement_method_name", "notice_lang_name",
])
LIVE_TYPES = (
    "Invitation for Bids",
    "Request for Expression of Interest",
    "Invitation for Prequalification",
)
PRE_TYPES = ("General Procurement Notice",)
AWARD_TYPES = ("Contract Award",)
ALL_TYPES = LIVE_TYPES + PRE_TYPES + AWARD_TYPES


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def pdt(v: Any) -> datetime | None:
    s = clean(v)
    if not s:
        return None
    candidates = [s, s[:10]]
    fmts = (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    )
    for candidate in candidates:
        normalized = candidate.replace("Z", "+0000")
        for fmt in fmts:
            try:
                dt = datetime.strptime(normalized, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        try:
            dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def get_page(session: requests.Session, notice_type: str, offset: int, rows: int) -> dict[str, Any]:
    params = {
        "format": "json",
        "rows": rows,
        "os": offset,
        "srt": "noticedate",
        "order": "desc",
        "fl": LIST_FIELDS,
        "notice_type": notice_type,
    }
    last = None
    for attempt in range(5):
        try:
            r = session.get(BASE, params=params, timeout=45)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("World Bank API returned non-object JSON")
        except Exception as exc:
            last = exc
            if attempt < 4:
                time.sleep(min(12, 2 ** attempt))
    raise RuntimeError(f"World Bank API failed for {notice_type}: {last!r}")


def row_to_record(r: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    nid = clean(r.get("id"))
    if not nid:
        return None
    typ = clean(r.get("notice_type"))
    pub = pdt(r.get("noticedate"))
    deadline = pdt(r.get("submission_deadline_date"))
    return {
        "candidate_id": f"WORLD-BANK:{nid}",
        "source": "WORLD_BANK_PROCUREMENT",
        "portal": "WORLD_BANK",
        "notice_id": nid,
        "title": clean(r.get("bid_description")) or clean(r.get("project_name")) or nid,
        "description": clean(r.get("bid_description")),
        "buyer": None,
        "country": clean(r.get("project_ctry_name")) or None,
        "project_id": clean(r.get("project_id")) or None,
        "project_name": clean(r.get("project_name")) or None,
        "reference": clean(r.get("bid_reference_no")) or None,
        "notice_type": typ or None,
        "notice_status": clean(r.get("notice_status")) or None,
        "procurement_group": clean(r.get("procurement_group")) or None,
        "procurement_method": clean(r.get("procurement_method_name")) or clean(r.get("procurement_method_code")) or None,
        "published": pub.isoformat() if pub else None,
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_time_raw": clean(r.get("submission_deadline_time")) or None,
        "notice_url": DETAIL + nid,
        "observed_at": now.isoformat(),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/WORLD_BANK_PROCUREMENT")))
    ap.add_argument("--max-pages", type=int, default=int(os.getenv("WB_MAX_PAGES", "20")), help="Maximum pages per notice type, not across all types.")
    ap.add_argument("--page-size", type=int, default=int(os.getenv("WB_PAGE_SIZE", "100")))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    live_by_id: dict[str, dict[str, Any]] = {}
    awards_by_id: dict[str, dict[str, Any]] = {}
    pre_by_id: dict[str, dict[str, Any]] = {}
    telemetry: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    totals_by_type: dict[str, int | None] = {}

    for notice_type in ALL_TYPES:
        for page in range(max(1, args.max_pages)):
            offset = page * args.page_size
            try:
                data = get_page(session, notice_type, offset, args.page_size)
            except Exception as exc:
                errors.append({"notice_type": notice_type, "page": page, "error": repr(exc)})
                break
            if notice_type not in totals_by_type:
                try:
                    totals_by_type[notice_type] = int(data.get("total"))
                except Exception:
                    totals_by_type[notice_type] = None
            rows = data.get("procnotices") or []
            if not isinstance(rows, list) or not rows:
                break
            telemetry.append({"notice_type": notice_type, "page": page, "offset": offset, "rows": len(rows)})
            for r in rows:
                if not isinstance(r, dict):
                    continue
                rec = row_to_record(r, now)
                if not rec:
                    continue
                nid = rec["notice_id"]
                # The type-specific query is authoritative for classification;
                # preserve any conflicting payload label without mixing grains.
                rec["query_notice_type"] = notice_type
                if notice_type in LIVE_TYPES:
                    deadline = pdt(r.get("submission_deadline_date"))
                    current = bool(deadline and deadline >= now)
                    live_by_id[nid] = {
                        **rec,
                        "grain": "NOTICE_FIRST_TENDER",
                        "current": current,
                        "route": {"document_urls": [], "route_status": "WORLD_BANK_NOTICE_DETAIL_PUBLIC"},
                    }
                elif notice_type in AWARD_TYPES:
                    awards_by_id[nid] = {
                        **rec,
                        "grain": "AWARD_NOTICE",
                        "current": False,
                        "supplier_resolution_status": "PENDING_DETAIL_PARSE",
                    }
                else:
                    pre_by_id[nid] = {**rec, "grain": "PRE_TENDER_RADAR", "current": True}
            if len(rows) < args.page_size:
                break

    live = sorted(live_by_id.values(), key=lambda x: (x.get("deadline") or "9999", x["candidate_id"]))
    current = [x for x in live if x.get("current")]
    awards = sorted(awards_by_id.values(), key=lambda x: x.get("published") or "", reverse=True)
    pre = sorted(pre_by_id.values(), key=lambda x: x.get("published") or "", reverse=True)
    write_jsonl(out / "raw.jsonl", live)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "awards.jsonl", awards)
    write_jsonl(out / "pre_tender.jsonl", pre)
    stats = {
        "source": "WORLD_BANK_PROCUREMENT",
        "grain": ["NOTICE_FIRST_TENDER", "AWARD_NOTICE", "PRE_TENDER_RADAR"],
        "raw_materialized": len(live),
        "current_materialized": len(current),
        "award_notices_materialized": len(awards),
        "pre_tender_materialized": len(pre),
        "api_records_seen": len(live_by_id) + len(awards_by_id) + len(pre_by_id),
        "totals_by_type": totals_by_type,
        "max_pages_per_type": args.max_pages,
        "page_size": args.page_size,
        "generated_at": now.isoformat(),
        "errors": errors,
        "telemetry": telemetry,
        "source_url": BASE,
        "semantics": "Each World Bank notice type is paginated independently for recall. Award notices remain AWARD_NOTICE until supplier/value detail is parsed; GPNs are PRE_TENDER_RADAR and never mixed into live opportunity counts.",
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not (live or awards or pre):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
