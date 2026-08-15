from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/BE_EPROC_PUBLIC"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://www.publicprocurement.be"
BDA = f"{BASE}/bda"
SEARCH_API = f"{BASE}/api/sea/search/publications"
NOW = datetime.now(timezone.utc)
BE_TZ = ZoneInfo("Europe/Brussels")
LOOKBACK_DAYS = max(1, min(365, int(os.getenv("LOOKBACK_DAYS", "14"))))
SCAN_DAYS = max(LOOKBACK_DAYS, min(730, int(os.getenv("BE_SCAN_DAYS", "120"))))
MAX_PAGES = max(1, min(500, int(os.getenv("BE_MAX_PAGES", "220"))))
PAGE_SIZE = max(25, min(250, int(os.getenv("BE_PAGE_SIZE", "100"))))


def clean(value):
    return " ".join(str(value or "").split())


def parse_dt(value):
    s = clean(value)
    if not s:
        return None
    try:
        if len(s) == 10:
            dt = datetime.fromisoformat(s + "T00:00:00")
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BE_TZ)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def pick_text(items, preferred=()):
    if not isinstance(items, list):
        return None
    rows = [x for x in items if isinstance(x, dict) and clean(x.get("text"))]
    if not rows:
        return None
    wanted = [clean(x).upper() for x in preferred if clean(x)] + ["NL", "FR", "EN", "DE"]
    for lang in wanted:
        for row in rows:
            if clean(row.get("language")).upper() == lang:
                return clean(row.get("text"))
    return clean(rows[0].get("text"))


def normalize(pub):
    if not isinstance(pub, dict):
        return None
    workspace = clean(pub.get("publicationWorkspaceId"))
    procedure_id = clean(pub.get("procedureId"))
    notice_ids = [clean(x) for x in (pub.get("noticeIds") or []) if clean(x)]
    ref = clean(pub.get("referenceNumber"))
    bda_refs = [clean(x) for x in (pub.get("publicationReferenceNumbersBDA") or []) if clean(x)]
    ted_refs = [clean(x) for x in (pub.get("publicationReferenceNumbersTED") or []) if clean(x)]
    dossier = pub.get("dossier") if isinstance(pub.get("dossier"), dict) else {}
    langs = pub.get("publicationLanguages") or []
    title = pick_text(dossier.get("titles"), langs)
    description = pick_text(dossier.get("descriptions"), langs)
    org = pub.get("organisation") if isinstance(pub.get("organisation"), dict) else {}
    buyer = pick_text(org.get("organisationNames"), langs)
    deadline = parse_dt(pub.get("vaultSubmissionDeadline"))
    published = parse_dt(pub.get("publicationDate") or ((pub.get("publishedAt") or [None])[-1] if isinstance(pub.get("publishedAt"), list) else pub.get("publishedAt")))
    cancelled = bool(pub.get("cancelledAt"))
    current = bool(deadline and deadline >= NOW and not cancelled)
    cpv = pub.get("cpvMainCode") if isinstance(pub.get("cpvMainCode"), dict) else {}
    cpv_code = clean(cpv.get("code")) or None
    cpv_label = pick_text(cpv.get("descriptions"), langs)
    identity = workspace or (notice_ids[0] if notice_ids else None) or procedure_id or ref
    if not identity:
        return None
    return {
        "candidate_id": f"BE-EPROC:{identity}",
        "source": "BE_EPROC_PUBLIC",
        "portal": "BE_EPROC",
        "notice_id": notice_ids[0] if notice_ids else (bda_refs[0] if bda_refs else ref or identity),
        "publication_workspace_id": workspace or None,
        "procedure_id": procedure_id or None,
        "reference_number": ref or None,
        "publication_reference_numbers_bda": bda_refs,
        "publication_reference_numbers_ted": ted_refs,
        "title": title or ref or identity,
        "buyer": buyer,
        "buyer_organisation_id": org.get("organisationId"),
        "deadline": deadline.isoformat() if deadline else None,
        "published": published.isoformat() if published else None,
        "current": current,
        "cancelled": cancelled,
        "publication_type": pub.get("publicationType"),
        "notice_subtype": pub.get("noticeSubType"),
        "procurement_method": dossier.get("procurementProcedureType"),
        "legal_basis": dossier.get("legalBasis"),
        "natures": pub.get("natures") or [],
        "nuts_codes": pub.get("nutsCodes") or [],
        "cpv": cpv_code,
        "cpv_label": cpv_label,
        "description": description,
        "ted_published": bool(pub.get("tedPublished")),
        "notice_url": BDA,
        "route": {
            "public_search_url": BDA,
            "search_api": SEARCH_API,
            "procedure_id": procedure_id or None,
            "publication_workspace_id": workspace or None,
            "notice_ids": notice_ids,
            "reference_number": ref or None,
        },
        "raw_publication": pub,
        "discovered_at": NOW.isoformat(),
    }


def main():
    chrome = os.getenv("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
    if not chrome:
        stats = {"source": "BE_EPROC_PUBLIC", "raw_materialized": 0, "current_materialized": 0, "generated_at": NOW.isoformat(), "errors": [{"type": "NO_SYSTEM_CHROME"}]}
        (OUT / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        raise SystemExit(2)

    from playwright.sync_api import sync_playwright

    pw = browser = context = page = None
    captured_headers = None
    first_data = None
    telemetry = []
    errors = []
    publications = []
    total_count = None
    pages_fetched = 0
    effective_page_size = PAGE_SIZE
    scan_cutoff = NOW - timedelta(days=SCAN_DAYS)
    raw_cutoff = NOW - timedelta(days=LOOKBACK_DAYS)

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, executable_path=chrome, args=["--no-sandbox"])
        context = browser.new_context(locale="en-GB")
        page = context.new_page()

        def on_request(req):
            nonlocal captured_headers
            try:
                if req.url.startswith(SEARCH_API) and req.method == "POST" and captured_headers is None:
                    captured_headers = req.all_headers()
            except Exception:
                pass

        def on_response(resp):
            nonlocal first_data
            try:
                if resp.url.startswith(SEARCH_API) and resp.status == 200 and first_data is None:
                    data = resp.json()
                    if isinstance(data, dict) and isinstance(data.get("publications"), list):
                        first_data = data
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)
        page.goto(BDA, wait_until="domcontentloaded", timeout=60000)
        for _ in range(50):
            if captured_headers and first_data:
                break
            page.wait_for_timeout(400)
        if not captured_headers or not first_data:
            raise RuntimeError("Belgian public BDA search bootstrap did not yield a 200 publication response")

        # Keep the anonymous public bearer/cookie/session only in memory. Never log or persist it.
        allowed = {"authorization", "content-type", "accept", "accept-language", "account-type", "origin", "referer"}
        replay_headers = {k: v for k, v in captured_headers.items() if k.lower() in allowed and v}
        replay_headers.setdefault("content-type", "application/json")
        replay_headers.setdefault("accept", "application/json, text/plain, */*")
        replay_headers.setdefault("account-type", "public")

        def fetch_page(page_no, page_size):
            payload = {"includeOrganisationChildren": True, "page": page_no, "pageSize": page_size}
            # First choice: BrowserContext APIRequestContext shares this anonymous browser cookie jar.
            try:
                rr = context.request.post(SEARCH_API, headers=replay_headers, data=payload, timeout=45000)
                text = rr.text()
                data = json.loads(text) if text else None
                telemetry.append({"page": page_no, "page_size": page_size, "method": "context.request", "status": rr.status, "bytes": len(text)})
                if rr.status == 200 and isinstance(data, dict) and isinstance(data.get("publications"), list):
                    return data
            except Exception as exc:
                telemetry.append({"page": page_no, "page_size": page_size, "method": "context.request", "error": repr(exc)})
            # Fallback: execute fetch inside the already-authorized public SPA origin.
            try:
                result = page.evaluate(
                    """async ({url,payload,headers}) => {
                      const r = await fetch(url,{method:'POST',headers,credentials:'include',body:JSON.stringify(payload)});
                      const text = await r.text();
                      return {status:r.status,text};
                    }""",
                    {"url": SEARCH_API, "payload": payload, "headers": replay_headers},
                )
                text = result.get("text") or ""
                data = json.loads(text) if text else None
                telemetry.append({"page": page_no, "page_size": page_size, "method": "page.fetch", "status": result.get("status"), "bytes": len(text)})
                if result.get("status") == 200 and isinstance(data, dict) and isinstance(data.get("publications"), list):
                    return data
            except Exception as exc:
                telemetry.append({"page": page_no, "page_size": page_size, "method": "page.fetch", "error": repr(exc)})
            return None

        # Prefer larger pages for efficient exhaustive recent/open traversal, fall back to the SPA's native 25.
        data = fetch_page(1, effective_page_size)
        if data is None and effective_page_size != 25:
            effective_page_size = 25
            data = first_data
        elif data is None:
            data = first_data

        for page_no in range(1, MAX_PAGES + 1):
            if page_no > 1:
                data = fetch_page(page_no, effective_page_size)
            if not data:
                if page_no == 1:
                    raise RuntimeError("Belgian publication API returned no usable first page")
                errors.append({"type": "PAGE_FETCH_FAILED", "page": page_no})
                break
            rows = data.get("publications") or []
            total_count = data.get("totalCount", total_count)
            if not rows:
                break
            publications.extend(rows)
            pages_fetched += 1

            pub_dates = [parse_dt(x.get("publicationDate")) for x in rows if isinstance(x, dict)]
            pub_dates = [x for x in pub_dates if x]
            # The public UI is newest-first. Once the oldest row on a complete page is outside
            # the configured scan horizon, later pages cannot add newer/open notices within it.
            if pub_dates and min(pub_dates) < scan_cutoff:
                break
            if len(rows) < effective_page_size:
                break

    except Exception as exc:
        errors.append({"type": "HARVEST_ERROR", "error": repr(exc)})
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass

    seen = {}
    for pub in publications:
        rec = normalize(pub)
        if not rec:
            continue
        published = parse_dt(rec.get("published"))
        # Preserve recent publications plus every future-deadline competition found in the scan horizon.
        if (published and published >= raw_cutoff) or rec.get("current"):
            seen[rec["candidate_id"]] = rec
    raw = list(seen.values())
    raw.sort(key=lambda x: (x.get("published") or "", x.get("candidate_id") or ""), reverse=True)
    current = [x for x in raw if x.get("current")]

    for name, rows in (("raw.jsonl", raw), ("current.jsonl", current)):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    stats = {
        "source": "BE_EPROC_PUBLIC",
        "raw_materialized": len(raw),
        "current_materialized": len(current),
        "future_deadline_materialized": len(current),
        "deadline_parsed": sum(bool(x.get("deadline")) for x in raw),
        "title_parsed": sum(bool(x.get("title")) for x in raw),
        "buyer_parsed": sum(bool(x.get("buyer")) for x in raw),
        "cancelled": sum(bool(x.get("cancelled")) for x in raw),
        "ted_published": sum(bool(x.get("ted_published")) for x in raw),
        "national_only": sum(not bool(x.get("ted_published")) for x in raw),
        "pages_fetched": pages_fetched,
        "page_size": effective_page_size,
        "api_total_count": total_count,
        "lookback_days": LOOKBACK_DAYS,
        "scan_days": SCAN_DAYS,
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "official_url": BDA,
        "public_search_api": SEARCH_API,
        "auth_mode": "ANONYMOUS_PUBLIC_SPA_SESSION",
        "credentials_persisted": False,
        "telemetry": telemetry,
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors or not raw:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
