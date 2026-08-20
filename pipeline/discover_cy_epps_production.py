from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from pipeline import discover_cy_epps_published_global_v3 as published
    from pipeline import resolve_cy_epps_workspaces as workspaces
    from pipeline.github_release_cache import download_asset, extract_tar_gz_bytes, load_json, release_age_seconds, release_by_tag
except ModuleNotFoundError:
    import discover_cy_epps_published_global_v3 as published
    import resolve_cy_epps_workspaces as workspaces
    from github_release_cache import download_asset, extract_tar_gz_bytes, load_json, release_age_seconds, release_by_tag

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/CYPRUS_EPPS"))
PROOF = Path(os.getenv("CY_EPPS_FULL_PROOF", "control/cy_epps_full_current_proof.json"))
MAX_AGE_HOURS = max(1.0, float(os.getenv("CY_EPPS_BASELINE_MAX_AGE_HOURS", "168")))
MAX_DELTA_PAGES = max(1, min(500, int(os.getenv("CY_EPPS_DELTA_MAX_PAGES", "80"))))
DELTA_DELAY = max(0.0, float(os.getenv("CY_EPPS_DELTA_PAGE_DELAY_SECONDS", "0.15")))
NOW = datetime.now(timezone.utc)
TERMINAL = {"NON_CURRENT"}


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line:
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_published_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None


def parse_deadline(value: Any) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def refresh_baseline_currentness(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    deadline = parse_deadline(row.get("deadline"))
    terminal = bool(row.get("terminal_evidence")) or row.get("current_state") == "NON_CURRENT"
    if deadline:
        current = deadline.astimezone(timezone.utc) >= NOW and not terminal
        row["current"] = current
        row["current_state"] = "CURRENT" if current else "NON_CURRENT"
        row["currentness_evidence"] = (
            "CY_EPPS_PROVEN_BASELINE_FUTURE_DEADLINE_RECHECKED"
            if current else "CY_EPPS_PROVEN_BASELINE_DEADLINE_EXPIRED_OR_TERMINAL"
        )
    elif terminal:
        row["current"] = False
        row["current_state"] = "NON_CURRENT"
    else:
        row["current"] = False
        row["current_state"] = "UNKNOWN"
        row["currentness_evidence"] = "CY_EPPS_PROVEN_BASELINE_LOST_CURRENTNESS_EVIDENCE"
    return row


def load_baseline():
    proof = load_json(PROOF)
    if proof.get("schema") != "CY_EPPS_FULL_CURRENT_UNIVERSE_PROOF_V1" or proof.get("pass") is not True:
        raise RuntimeError("CY_EPPS_FULL_CURRENT_PROOF_NOT_GREEN")
    if proof.get("exact_transport_reconciliation") is not True or proof.get("currentness_complete") is not True:
        raise RuntimeError("CY_EPPS_FULL_CURRENT_PROOF_NOT_COMPLETE")
    if int(proof.get("unknown_currentness") or 0) != 0:
        raise RuntimeError("CY_EPPS_FULL_CURRENT_PROOF_HAS_UNKNOWN")
    tag = clean(proof.get("release_tag"))
    release = release_by_tag(tag)
    age_seconds = release_age_seconds(release, now=NOW)
    if age_seconds is None or age_seconds > MAX_AGE_HOURS * 3600:
        raise RuntimeError(f"CY_EPPS_BASELINE_STALE age_hours={(age_seconds or -1)/3600:.2f} max={MAX_AGE_HOURS}")
    body = download_asset(release, "cy-epps-current-full-merged.tar.gz")
    temp = Path(tempfile.mkdtemp(prefix="cy-epps-proven-"))
    extract_tar_gz_bytes(body, temp)
    stats = load_json(temp / "cy-workspaces-merged" / "stats.json")
    if stats.get("listing_contract") != "CY_EPPS_PUBLIC_CFT_WORKSPACE_SHARDED_V2":
        raise RuntimeError("CY_EPPS_CACHED_CURRENT_CONTRACT_MISMATCH")
    if stats.get("currentness_complete") is not True or stats.get("live_coverage_credit_allowed") is not True:
        raise RuntimeError("CY_EPPS_CACHED_CURRENT_NOT_COMPLETE")
    rows = [refresh_baseline_currentness(row) for row in iter_jsonl(temp / "cy-workspaces-merged" / "resolved.jsonl")]
    published_at = release.get("published_at") or release.get("created_at")
    published_dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)
    # Publication dates exposed by the registry are day-grain. Read through one
    # full day before the Release timestamp to guarantee overlap at the boundary.
    cutoff_date = (published_dt.astimezone(workspaces.CY_TZ).date() - timedelta(days=1))
    return proof, release, age_seconds, stats, rows, cutoff_date, temp


def collect_delta(cutoff_date: date):
    session = published.base.requests.Session()
    session.headers.update({"User-Agent": published.base.UA, "Accept": "text/html,application/xhtml+xml,*/*"})
    pager_prefix = None
    total = None
    total_pages = None
    recent_rows = []
    telemetry = []
    cutoff_reached = False
    for page in range(1, MAX_DELTA_PAGES + 1):
        response = published.base.fetch(session, published.base.page_url(page, pager_prefix))
        rows, proof = published.base.parse_page(response, page)
        if total is None:
            total = int(proof["total_reported"])
            total_pages = int(proof["total_pages"])
            pager_prefix = clean(proof.get("pager_prefix")) or None
        elif int(proof["total_reported"]) != total or int(proof["total_pages"]) != total_pages:
            raise RuntimeError(f"CY_EPPS_DELTA_TOTAL_DRIFT page={page}")
        dates = [parse_published_date(row.get("published")) for row in rows]
        known_dates = [d for d in dates if d is not None]
        telemetry.append({
            "page": page,
            "rows": len(rows),
            "known_publication_dates": len(known_dates),
            "newest_date": max(known_dates).isoformat() if known_dates else None,
            "oldest_date": min(known_dates).isoformat() if known_dates else None,
        })
        recent_rows.extend(rows)
        if known_dates and max(known_dates) <= cutoff_date:
            cutoff_reached = True
            break
        if DELTA_DELAY:
            time.sleep(DELTA_DELAY)
    if not cutoff_reached:
        raise RuntimeError(f"CY_EPPS_DELTA_CUTOFF_NOT_REACHED max_pages={MAX_DELTA_PAGES} cutoff={cutoff_date}")
    return recent_rows, telemetry, total, total_pages


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    temp = None
    proof = {}
    release = {}
    age_seconds = None
    baseline_stats = {}
    baseline_rows = []
    cutoff_date = None
    try:
        proof, release, age_seconds, baseline_stats, baseline_rows, cutoff_date, temp = load_baseline()
    except Exception as exc:
        errors.append({"stage": "baseline", "error": repr(exc)})

    delta_rows = []
    delta_telemetry = []
    total_reported = None
    total_pages = None
    if not errors:
        try:
            delta_rows, delta_telemetry, total_reported, total_pages = collect_delta(cutoff_date)
        except Exception as exc:
            errors.append({"stage": "published_delta", "error": repr(exc)})

    records = {clean(row.get("resource_id")): row for row in baseline_rows if clean(row.get("resource_id"))}
    touched_meta = {}
    if not errors:
        for row in delta_rows:
            if not row.get("competition_relevant"):
                continue
            rid = clean(row.get("resource_id"))
            if not rid:
                errors.append({"stage": "published_delta", "error": "COMPETITION_ROW_WITHOUT_RESOURCE_ID", "notice_id": row.get("notice_id")})
                break
            meta = touched_meta.setdefault(rid, {
                "resource_id": rid,
                "title": row.get("title"),
                "notice_id": row.get("notice_id"),
                "document_id": row.get("document_id"),
                "notice_url": row.get("notice_url"),
                "publication_count": 0,
            })
            meta["publication_count"] += 1

    workspace_refresh_errors = []
    refreshed = 0
    if not errors:
        session = workspaces.requests.Session()
        session.headers.update({"User-Agent": workspaces.UA, "Accept": "text/html,application/xhtml+xml,*/*"})
        for rid, meta in touched_meta.items():
            try:
                workspace = workspaces.fetch_workspace(session, rid)
                row = workspaces.classify(meta, workspace)
                records[rid] = row
                refreshed += 1
            except Exception as exc:
                workspace_refresh_errors.append({"resource_id": rid, "error": repr(exc)})
            if workspaces.DELAY:
                time.sleep(workspaces.DELAY)
    if workspace_refresh_errors:
        errors.append({"stage": "workspace_delta", "error_count": len(workspace_refresh_errors), "sample": workspace_refresh_errors[:20]})

    rows = sorted(records.values(), key=lambda x: clean(x.get("resource_id")))
    current = [row for row in rows if row.get("current") is True]
    unknown = [row for row in rows if row.get("current_state") == "UNKNOWN"]
    complete = bool(not errors and baseline_rows and delta_telemetry and not unknown)
    write_jsonl(OUT / "resolved.jsonl", rows)
    write_jsonl(OUT / "current.jsonl", current)
    write_jsonl(OUT / "unknown.jsonl", unknown)
    stats = {
        "source": "CYPRUS_EPPS",
        "portal": "CYPRUS_EPPS",
        "listing_contract": "CY_EPPS_PROVEN_FULL_BASELINE_PLUS_PUBLISHED_DELTA_V2",
        "baseline_release_tag": proof.get("release_tag"),
        "baseline_release_published_at": release.get("published_at") if isinstance(release, dict) else None,
        "baseline_age_hours": round(age_seconds / 3600, 3) if age_seconds is not None else None,
        "baseline_max_age_hours": MAX_AGE_HOURS,
        "delta_cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
        "delta_pages_fetched": len(delta_telemetry),
        "delta_max_pages": MAX_DELTA_PAGES,
        "delta_total_reported": total_reported,
        "delta_total_pages": total_pages,
        "delta_publication_rows": len(delta_rows),
        "delta_competition_resources_touched": len(touched_meta),
        "delta_workspaces_refreshed": refreshed,
        "resources_materialized": len(rows),
        "current_materialized": len(current),
        "unknown_currentness": len(unknown),
        "enumeration_exhausted": complete,
        "enumeration_complete": complete,
        "live_candidate_capable": bool(current),
        "live_coverage_credit_allowed": complete and bool(current),
        "errors": errors,
        "delta_telemetry": delta_telemetry,
        "generated_at": NOW.isoformat(),
        "semantics": (
            "Production Cyprus lane starts from a recent green full-current-universe Release, recalculates cached deadline currentness, then traverses newest national Published Notices pages until it overlaps one full local calendar day before the baseline Release. "
            "Every competition resource touched in that overlap/new interval is re-resolved through its public CfT workspace, covering new and modified procedures. The delta is complete only when the publication-date cutoff is actually reached before the hard page bound, official page totals remain stable, all workspace refreshes succeed, and zero UNKNOWN currentness remains. "
            "Any stale/missing full proof, cutoff miss, resource identity gap, workspace failure or UNKNOWN classification keeps live coverage fail-closed."
        ),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if temp:
        shutil.rmtree(temp, ignore_errors=True)
    if not complete:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
