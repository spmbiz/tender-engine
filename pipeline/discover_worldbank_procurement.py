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
    "id","notice_type","notice_status","noticedate","submission_deadline_date","submission_deadline_time",
    "project_ctry_name","project_id","project_name","bid_reference_no","bid_description","procurement_group",
    "procurement_method_code","procurement_method_name","notice_lang_name"
])
LIVE_TYPES = {"Invitation for Bids", "Request for Expression of Interest", "Invitation for Prequalification"}
PRE_TYPES = {"General Procurement Notice"}
AWARD_TYPES = {"Contract Award"}


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def pdt(v: Any) -> datetime | None:
    s = clean(v)
    if not s:
        return None
    for candidate in (s, s[:10]):
        try:
            dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def get_page(session: requests.Session, offset: int, rows: int) -> dict[str, Any]:
    params = {"format":"json","rows":rows,"os":offset,"srt":"noticedate","order":"desc","fl":LIST_FIELDS}
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
    raise RuntimeError(f"World Bank API failed: {last!r}")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(os.getenv("DISCOVERY_OUT", "discovery/global/WORLD_BANK_PROCUREMENT")))
    ap.add_argument("--max-pages", type=int, default=int(os.getenv("WB_MAX_PAGES", "40")))
    ap.add_argument("--page-size", type=int, default=int(os.getenv("WB_PAGE_SIZE", "100")))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    live: list[dict[str, Any]] = []
    awards: list[dict[str, Any]] = []
    pre: list[dict[str, Any]] = []
    seen: set[str] = set()
    telemetry = []
    total_reported = None

    for page in range(max(1, args.max_pages)):
        offset = page * args.page_size
        data = get_page(session, offset, args.page_size)
        if total_reported is None:
            try: total_reported = int(data.get("total"))
            except Exception: total_reported = None
        rows = data.get("procnotices") or []
        if not isinstance(rows, list) or not rows:
            break
        telemetry.append({"page":page,"offset":offset,"rows":len(rows)})
        for r in rows:
            if not isinstance(r, dict):
                continue
            nid = clean(r.get("id"))
            if not nid or nid in seen:
                continue
            seen.add(nid)
            typ = clean(r.get("notice_type"))
            pub = pdt(r.get("noticedate"))
            deadline = pdt(r.get("submission_deadline_date"))
            base = {
                "candidate_id": f"WORLD-BANK:{nid}",
                "source":"WORLD_BANK_PROCUREMENT",
                "portal":"WORLD_BANK",
                "notice_id":nid,
                "title":clean(r.get("bid_description")) or clean(r.get("project_name")) or nid,
                "description":clean(r.get("bid_description")),
                "buyer":None,
                "country":clean(r.get("project_ctry_name")) or None,
                "project_id":clean(r.get("project_id")) or None,
                "project_name":clean(r.get("project_name")) or None,
                "reference":clean(r.get("bid_reference_no")) or None,
                "notice_type":typ or None,
                "notice_status":clean(r.get("notice_status")) or None,
                "procurement_group":clean(r.get("procurement_group")) or None,
                "procurement_method":clean(r.get("procurement_method_name")) or clean(r.get("procurement_method_code")) or None,
                "published":pub.isoformat() if pub else None,
                "deadline":deadline.isoformat() if deadline else None,
                "notice_url":DETAIL+nid,
                "observed_at":now.isoformat(),
            }
            if typ in LIVE_TYPES:
                current = bool(deadline and deadline >= now)
                live.append({**base,"grain":"NOTICE_FIRST_TENDER","current":current,"route":{"document_urls":[],"route_status":"WORLD_BANK_NOTICE_DETAIL_PUBLIC"}})
            elif typ in AWARD_TYPES:
                awards.append({**base,"grain":"AWARD_NOTICE","current":False,"supplier_resolution_status":"PENDING_DETAIL_PARSE"})
            elif typ in PRE_TYPES:
                pre.append({**base,"grain":"PRE_TENDER_RADAR","current":True})
        if len(rows) < args.page_size:
            break

    current = [x for x in live if x.get("current")]
    write_jsonl(out / "raw.jsonl", live)
    write_jsonl(out / "current.jsonl", current)
    write_jsonl(out / "awards.jsonl", awards)
    write_jsonl(out / "pre_tender.jsonl", pre)
    stats = {
        "source":"WORLD_BANK_PROCUREMENT",
        "grain":["NOTICE_FIRST_TENDER","AWARD_NOTICE","PRE_TENDER_RADAR"],
        "raw_materialized":len(live),
        "current_materialized":len(current),
        "award_notices_materialized":len(awards),
        "pre_tender_materialized":len(pre),
        "api_records_seen":len(seen),
        "total_reported":total_reported,
        "generated_at":now.isoformat(),
        "errors":[],
        "telemetry":telemetry,
        "source_url":BASE,
        "semantics":"Award notices remain AWARD_NOTICE until supplier/value detail is parsed; pre-tender notices are never mixed into live opportunity counts."
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not seen:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
