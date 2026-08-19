from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from discover_uk_pcs_current_direct import (
    URL,
    NOTICE_TYPE,
    PAGE_TARGET,
    POST_TIMEOUT_MS,
    bootstrap_current_form,
    page_markers,
    parse_rows,
)

OUT = Path("control/pcs_stateful_pager_probe.json")


def serialize_html_form(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if not form:
        raise RuntimeError("PCS_RESPONSE_FORM_MISSING")
    data: dict[str, str] = {}
    for node in form.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if not name or node.has_attr("disabled"):
            continue
        if node.name == "input":
            typ = (node.get("type") or "text").lower()
            if typ in {"checkbox", "radio"} and not node.has_attr("checked"):
                continue
            data[name] = node.get("value") or ""
        elif node.name == "select":
            selected = node.find("option", selected=True) or node.find("option")
            data[name] = (selected.get("value") if selected else "") or ""
        else:
            data[name] = node.get_text() or ""
    return data


async def post_state(context, state: dict[str, str], *, target: str, page_value: int) -> tuple[str, int]:
    form = copy.deepcopy(state)
    form["__EVENTTARGET"] = target
    form["__EVENTARGUMENT"] = ""
    form[PAGE_TARGET] = str(page_value)
    response = await context.request.post(URL, form=form, timeout=POST_TIMEOUT_MS)
    text = await response.text()
    if response.status >= 400:
        raise RuntimeError(f"PCS_STATEFUL_POST_HTTP_{response.status}")
    return text, response.status


def client_state_debug(state: dict[str, str]):
    out = {}
    for key, value in state.items():
        low = key.lower()
        if "clientstate" in low or "pageselect" in low or "doctype" in low:
            out[key] = {"len": len(str(value)), "prefix": str(value)[:300]}
    return out


async def main():
    payload = {
        "schema": "PCS_STATEFUL_FILTERED_PAGER_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": [],
    }
    records = {}
    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            landing = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            payload["landing_status"] = landing.status if landing else None
            base, filter_meta = await bootstrap_current_form(page)
            payload["filter"] = filter_meta
            payload["base_notice_type"] = base.get(NOTICE_TYPE)
            payload["base_state_debug"] = client_state_debug(base)

            # Empirically, a pager event from the selected UI state materializes
            # the true Current Opportunity result universe even when a Search
            # postback returns the stale all-notices page 1. Capture that response
            # and, crucially, use ITS returned ASP.NET state for every next post.
            html2_boot, status = await post_state(context, base, target=PAGE_TARGET, page_value=2)
            p2, tp2, tr2, _ = page_markers(html2_boot)
            state = serialize_html_form(html2_boot)
            payload["bootstrap_page2"] = {
                "page": p2, "total_pages": tp2, "total_reported": tr2, "status": status,
                "notice_type": state.get(NOTICE_TYPE),
                "state_debug": client_state_debug(state),
            }
            if p2 != 2 or not tp2 or not tr2:
                raise RuntimeError(f"FILTERED_BOOTSTRAP_FAILED:{p2}/{tp2}/{tr2}")

            expected_pages, expected_total = tp2, tr2

            # Walk 1 -> 4, each time serializing the response form and using it
            # for the subsequent page. This tests whether state continuity fixes
            # the stale-page contract mismatch.
            for wanted in (1, 2, 3, 4):
                html, status = await post_state(context, state, target=PAGE_TARGET, page_value=wanted)
                page_no, total_pages, total_reported, parsed = parse_rows(html, records)
                state = serialize_html_form(html)
                item = {
                    "requested": wanted,
                    "page": page_no,
                    "total_pages": total_pages,
                    "total_reported": total_reported,
                    "rows_parsed": parsed,
                    "status": status,
                    "notice_type": state.get(NOTICE_TYPE),
                    "state_debug": client_state_debug(state),
                }
                payload["pages"].append(item)
                if page_no != wanted or total_pages != expected_pages or total_reported != expected_total:
                    raise RuntimeError(
                        f"STATEFUL_CONTRACT_MISMATCH requested={wanted} observed={page_no}/{total_pages}/{total_reported} "
                        f"expected={expected_pages}/{expected_total}"
                    )

            payload["unique_candidate_ids"] = len(records)
            payload["filtered_total"] = expected_total
            payload["filtered_total_pages"] = expected_pages
            payload["progress_proven"] = [x["page"] for x in payload["pages"]] == [1, 2, 3, 4]
            payload["stateful_filter_stable"] = payload["progress_proven"] and all(
                x["total_reported"] == expected_total for x in payload["pages"]
            )
            await browser.close()
    except BaseException as exc:
        payload["error"] = repr(exc)
        payload["progress_proven"] = False
        payload["stateful_filter_stable"] = False

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
