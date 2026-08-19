from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

BASE = "https://www.eprocurement.gov.cy"
RID = re.compile(r"resourceId=(\d+)", re.I)
CAPTCHA = re.compile(r"captcha|κωδικό captcha|type the code shown", re.I)


def clean(v):
    return " ".join(str(v or "").split())


async def main():
    pages=[]
    seen=set()
    async with async_playwright() as pw:
        chrome=os.getenv("CHROME_BIN") or None
        browser=await pw.chromium.launch(headless=True,executable_path=chrome)
        context=await browser.new_context(viewport={"width":1440,"height":1000})
        page=await context.new_page()
        bootstrap={}
        try:
            r=await page.goto(f"{BASE}/epps/home.do",wait_until="domcontentloaded",timeout=90000)
            bootstrap["status"]=r.status if r else None
            bootstrap["url"]=page.url
            bootstrap["title"]=await page.title()
            bootstrap["cookies"]=len(await context.cookies())
            await page.wait_for_timeout(1200)
        except Exception as exc:
            bootstrap["error"]=repr(exc)

        selected=quote("quickSearchAction.do?searchSelect=4&latest=true",safe="")
        for pg in range(1,6):
            url=(
                f"{BASE}/epps/quickSearchAction.do?latest=true&searchSelect=4&selectedItem={selected}"
                f"&T01_ps=100&d-3680175-n=1&d-3680175-o=2&d-3680175-p={pg}&d-3680175-s=deadline"
            )
            item={"requested_page":pg,"url":url}
            try:
                r=await page.goto(url,wait_until="domcontentloaded",timeout=90000)
                await page.wait_for_timeout(1200)
                html=await page.content()
                body=clean(await page.locator("body").inner_text())
                ids=[]
                for rid in RID.findall(html):
                    if rid not in ids: ids.append(rid)
                item.update({
                    "status":r.status if r else None,
                    "final_url":page.url,
                    "title":await page.title(),
                    "html_bytes":len(html.encode("utf-8",errors="ignore")),
                    "body_chars":len(body),
                    "captcha":bool(CAPTCHA.search(html) or CAPTCHA.search(body)),
                    "resource_ids":ids[:150],
                    "resource_id_count":len(ids),
                    "new_resource_ids":sum(1 for x in ids if x not in seen),
                    "body_sample":body[:5000],
                })
                seen.update(ids)
            except Exception as exc:
                item["error"]=repr(exc)
            pages.append(item)
        await browser.close()
    payload={
        "schema":"CYPRUS_QUICKSEARCH_BROWSER_PROBE_V1",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "bootstrap":bootstrap,
        "pages":pages,
        "unique_resource_ids":len(seen),
        "captcha_seen":any(x.get("captcha") for x in pages),
        "progress_proven":len(seen)>0 and sum(1 for x in pages if (x.get("new_resource_ids") or 0)>0)>=2,
    }
    Path("control").mkdir(exist_ok=True)
    Path("control/cyprus_quicksearch_browser_probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=="__main__": asyncio.run(main())
