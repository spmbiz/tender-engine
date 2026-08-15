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
    if isinstance(items, str):
        return clean(items) or None
    if isinstance(items, dict):
        for key in ("text", "name", "value", "label"):
            if clean(items.get(key)):
                return clean(items.get(key))
        items = list(items.values())
    if not isinstance(items, list):
        return None
    rows = [x for x in items if isinstance(x, dict) and clean(x.get("text"))]
    if rows:
        wanted = [clean(x).upper() for x in preferred if clean(x)] + ["NL", "FR", "EN", "DE"]
        for lang in wanted:
            for row in rows:
                if clean(row.get("language")).upper() == lang:
                    return clean(row.get("text"))
        return clean(rows[0].get("text"))
    for item in items:
        if isinstance(item, str) and clean(item):
            return clean(item)
        if isinstance(item, dict):
            for key in ("name", "value", "label"):
                if clean(item.get(key)):
                    return clean(item.get(key))
    return None


def buyer_from(pub, langs):
    org = pub.get("organisation") if isinstance(pub.get("organisation"), dict) else {}
    candidates = [
        org.get("organisationNames"), org.get("names"), org.get("name"),
        pub.get("organisationName"), pub.get("buyerName"), pub.get("contractingAuthorityName"),
    ]
    for value in candidates:
        text = pick_text(value, langs)
        if text:
            return text, org
    return None, org


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
    buyer, org = buyer_from(pub, langs)
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
        "buyer_organisation_id": org.get("organisationId") or pub.get("organisationId"),
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
    captured_payload = None
    first_data = None
    telemetry = []
    errors = []
    publications = []
    total_count = None
    pages_fetched = 0
    paginator_candidates = []
    scan_cutoff = NOW - timedelta(days=SCAN_DAYS)
    raw_cutoff = NOW - timedelta(days=LOOKBACK_DAYS)

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, executable_path=chrome, args=["--no-sandbox"])
        context = browser.new_context(locale="en-GB")
        page = context.new_page()

        def on_request(req):
            nonlocal captured_payload
            try:
                if req.url.startswith(SEARCH_API) and req.method == "POST" and captured_payload is None:
                    raw = req.post_data or ""
                    payload = json.loads(raw) if raw else None
                    if isinstance(payload, dict):
                        captured_payload = payload
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
            if captured_payload and first_data:
                break
            page.wait_for_timeout(400)
        if not captured_payload or not first_data:
            raise RuntimeError("Belgian public BDA bootstrap did not yield a complete publication request/response pair")

        native_page_size = int(captured_payload.get("pageSize") or 25)

        def button_metadata():
            result = []
            buttons = page.locator("button")
            try:
                count = min(buttons.count(), 120)
            except Exception:
                return result
            for i in range(count):
                b = buttons.nth(i)
                try:
                    result.append({
                        "index": i,
                        "text": clean(b.inner_text(timeout=1000)),
                        "aria": clean(b.get_attribute("aria-label")),
                        "title": clean(b.get_attribute("title")),
                        "class": clean(b.get_attribute("class")),
                        "disabled": b.is_disabled(),
                    })
                except Exception:
                    continue
            return result

        def find_next_button():
            selectors = [
                "button.mat-mdc-paginator-navigation-next",
                "button.mat-paginator-navigation-next",
                "button[aria-label='Next page']",
                "button[aria-label='Volgende pagina']",
                "button[aria-label='Page suivante']",
                "button[aria-label='Nächste Seite']",
                "button[title='Next page']",
            ]
            for selector in selectors:
                loc = page.locator(selector)
                try:
                    if loc.count() and loc.first.is_visible() and not loc.first.is_disabled():
                        return loc.first, selector
                except Exception:
                    pass
            hints = ("next", "volgende", "suivant", "suivante", "nächste", "chevron_right", "arrow_forward")
            buttons = page.locator("button")
            try:
                count = min(buttons.count(), 120)
            except Exception:
                count = 0
            for i in range(count):
                b = buttons.nth(i)
                try:
                    meta = " ".join([
                        clean(b.inner_text(timeout=800)), clean(b.get_attribute("aria-label")),
                        clean(b.get_attribute("title")), clean(b.get_attribute("class")),
                    ]).lower()
                    if any(h in meta for h in hints) and b.is_visible() and not b.is_disabled():
                        return b, f"button-index:{i}"
                except Exception:
                    continue
            return None, None

        def fetch_next_via_official_ui(target_page):
            nonlocal paginator_candidates
            button, selector = find_next_button()
            if button is None:
                paginator_candidates = button_metadata()
                telemetry.append({"page": target_page, "method": "official_ui_paginator", "error": "NEXT_BUTTON_NOT_FOUND", "button_count": len(paginator_candidates)})
                return None
            try:
                with page.expect_response(lambda r: r.url.startswith(SEARCH_API) and r.status == 200, timeout=25000) as info:
                    button.click(force=True)
                resp = info.value
                data = resp.json()
                rows = data.get("publications") if isinstance(data, dict) else None
                telemetry.append({"page": target_page, "page_size": native_page_size, "method": "official_ui_paginator", "selector": selector, "status": resp.status, "rows": len(rows) if isinstance(rows, list) else None})
                if isinstance(data, dict) and isinstance(rows, list):
                    page.wait_for_timeout(120)
                    return data
            except Exception as exc:
                paginator_candidates = button_metadata()
                telemetry.append({"page": target_page, "method": "official_ui_paginator", "selector": selector, "error": repr(exc), "button_count": len(paginator_candidates)})
            return None

        data = first_data
        for page_no in range(1, MAX_PAGES + 1):
            if page_no > 1:
                data = fetch_next_via_official_ui(page_no)
            if not data:
                if page_no == 1:
                    raise RuntimeError("Belgian publication UI returned no usable first page")
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
            if pub_dates and max(pub_dates) < scan_cutoff:
                break
            if len(rows) < native_page_size:
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
        "page_size": int(captured_payload.get("pageSize") or 25) if isinstance(captured_payload, dict) else None,
        "api_total_count": total_count,
        "lookback_days": LOOKBACK_DAYS,
        "scan_days": SCAN_DAYS,
        "generated_at": NOW.isoformat(),
        "errors": errors,
        "official_url": BDA,
        "public_search_api": SEARCH_API,
        "auth_mode": "ANONYMOUS_PUBLIC_SPA_UI",
        "credentials_persisted": False,
        "request_schema_keys": sorted(captured_payload.keys()) if isinstance(captured_payload, dict) else [],
        "telemetry": telemetry,
        "paginator_candidates": paginator_candidates[:120],
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors or not raw:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
