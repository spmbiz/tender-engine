from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

URL = "https://www.publiccontractsscotland.gov.uk/search/Search_MainPage.aspx"
PAGE_TARGET = "ctl00$maincontent$PagingHelperTop$ddPageSelect"
PAGE_BOTTOM = "ctl00$maincontent$PagingHelperBottom$ddPageSelect"


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def page_markers(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    m = re.search(r"Showing\s+page\s+(\d+)\s+of\s+(\d+)", text, re.I)
    total = re.search(r"total\s+([\d,]+)\s+items", text, re.I)
    refs = re.findall(r"Reference\s*No:\s*([^\s<]+)", html, re.I)
    return {
        "page": int(m.group(1)) if m else None,
        "total_pages": int(m.group(2)) if m else None,
        "total_items": int(total.group(1).replace(",", "")) if total else None,
        "refs": refs[:20],
    }


def form_from_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if form is None:
        raise RuntimeError("PCS_FORM_MISSING_IN_POST_RESPONSE")
    data: dict[str, Any] = {}
    for node in form.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if not name or node.has_attr("disabled"):
            continue
        tag = (node.name or "").lower()
        if tag == "input":
            typ = (node.get("type") or "text").lower()
            if typ in {"checkbox", "radio"} and not node.has_attr("checked"):
                continue
            data[name] = node.get("value") or ""
        elif tag == "select":
            selected = node.find_all("option", selected=True)
            if not selected:
                first = node.find("option")
                data[name] = (first.get("value") or "") if first else ""
            elif node.has_attr("multiple"):
                data[name] = [(o.get("value") or "") for o in selected]
            else:
                data[name] = selected[0].get("value") or ""
        else:
            data[name] = node.get_text() or ""
    return data


async def browser_form(page) -> dict[str, Any]:
    return await page.locator("#aspnetForm").evaluate("""form => {
      const data = {};
      for (const el of Array.from(form.elements || [])) {
        if (!el.name || el.disabled) continue;
        const tag = (el.tagName || '').toLowerCase();
        const type = (el.type || '').toLowerCase();
        if ((type === 'checkbox' || type === 'radio') && !el.checked) continue;
        if (tag === 'select' && el.multiple) data[el.name] = Array.from(el.selectedOptions || [], o => o.value);
        else data[el.name] = el.value ?? '';
      }
      return data;
    }""")


async def select_current(page) -> tuple[str, str, str]:
    selects = page.locator("select")
    for idx in range(await selects.count()):
        sel = selects.nth(idx)
        options = await sel.evaluate(
            "el => Array.from(el.options||[], o => ({text:(o.textContent||'').trim(), value:o.value}))"
        )
        for option in options or []:
            text = clean(option.get("text"))
            if re.search(r"\bcurrent\s+opportunit(?:y|ies)\b", text, re.I):
                value = str(option.get("value") or "")
                await sel.select_option(value=value)
                name = str(await sel.get_attribute("name") or "")
                if not name:
                    raise RuntimeError("PCS_CURRENT_FILTER_SELECT_HAS_NO_NAME")
                return name, value, text
    raise RuntimeError("PCS_CURRENT_OPPORTUNITY_FILTER_NOT_FOUND")


async def post_page(context, base_form: dict[str, Any], wanted: int, *, current_name: str, current_value: str) -> tuple[str, dict[str, Any]]:
    form = copy.deepcopy(base_form)
    form[current_name] = current_value
    form["__EVENTTARGET"] = PAGE_TARGET
    form["__EVENTARGUMENT"] = ""
    form[PAGE_TARGET] = str(wanted)
    # Keep both pager controls aligned. Older probes left the bottom selector on
    # page 1; aligning them avoids an ambiguous WebForms postback contract.
    if PAGE_BOTTOM in form:
        form[PAGE_BOTTOM] = str(wanted)
    response = await context.request.post(URL, form=form, timeout=120000)
    html = await response.text()
    if response.status >= 400:
        raise RuntimeError(f"PCS_STATE_CHAIN_HTTP_{response.status}")
    return html, {
        "requested_page": wanted,
        "status": response.status,
        "bytes": len(html.encode("utf-8", errors="ignore")),
        "markers": page_markers(html),
        "viewstate_len": len(str(form.get("__VIEWSTATE") or "")),
        "eventvalidation_len": len(str(form.get("__EVENTVALIDATION") or "")),
    }


async def main() -> None:
    out: dict[str, Any] = {
        "schema": "PCS_FILTERED_STATE_CHAIN_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "errors": [],
        "steps": [],
    }
    try:
        async with async_playwright() as pw:
            chrome = os.getenv("CHROME_BIN") or None
            browser = await pw.chromium.launch(headless=True, executable_path=chrome)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            try:
                landing = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
                out["landing_status"] = landing.status if landing else None
                current_name, current_value, current_text = await select_current(page)
                out["current_filter"] = {
                    "name": current_name,
                    "value": current_value,
                    "text": current_text,
                }
                state = await browser_form(page)
                state[current_name] = current_value

                # Page 1 is special on PCS: posting a page-1 value from the initial
                # all-notices state does not force the filtered pager. A transition
                # to page 2 does. Once the response carries filtered WebForms state,
                # we prove that state can navigate back to page 1 and forward again.
                html2, meta2 = await post_page(
                    context, state, 2, current_name=current_name, current_value=current_value
                )
                out["steps"].append(meta2)
                state2 = form_from_html(html2)

                html1, meta1 = await post_page(
                    context, state2, 1, current_name=current_name, current_value=current_value
                )
                out["steps"].append(meta1)
                state1 = form_from_html(html1)

                html3, meta3 = await post_page(
                    context, state1, 3, current_name=current_name, current_value=current_value
                )
                out["steps"].append(meta3)
                state3 = form_from_html(html3)

                total_pages = (meta3.get("markers") or {}).get("total_pages")
                if isinstance(total_pages, int) and total_pages >= 3:
                    html_last, meta_last = await post_page(
                        context,
                        state3,
                        total_pages,
                        current_name=current_name,
                        current_value=current_value,
                    )
                    out["steps"].append(meta_last)

                markers = [x.get("markers") or {} for x in out["steps"]]
                totals = {(m.get("total_pages"), m.get("total_items")) for m in markers}
                wanted_pages = [2, 1, 3]
                observed_prefix = [m.get("page") for m in markers[:3]]
                last_ok = True
                if len(markers) >= 4:
                    last_ok = markers[-1].get("page") == markers[-1].get("total_pages")
                ref_sets = [set(m.get("refs") or []) for m in markers[:3]]
                distinct_refs = all(
                    ref_sets[i].isdisjoint(ref_sets[j])
                    for i in range(len(ref_sets))
                    for j in range(i + 1, len(ref_sets))
                )
                out["state_chain_proven"] = bool(
                    observed_prefix == wanted_pages
                    and len(totals) == 1
                    and next(iter(totals))[0] not in (None, 0)
                    and next(iter(totals))[1] not in (None, 0)
                    and last_ok
                    and distinct_refs
                )
                out["filtered_total_pages"] = markers[0].get("total_pages") if markers else None
                out["filtered_total_items"] = markers[0].get("total_items") if markers else None
            finally:
                await browser.close()
    except Exception as exc:
        out["errors"].append({"type": "PCS_FILTERED_STATE_CHAIN_PROBE_ERROR", "error": repr(exc)})
        out["state_chain_proven"] = False

    Path("control").mkdir(exist_ok=True)
    Path("control/pcs_filtered_state_chain_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out.get("state_chain_proven"):
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
