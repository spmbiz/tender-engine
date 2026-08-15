from __future__ import annotations

import json, os, re, shutil
from pathlib import Path

OUT=Path(os.getenv('DISCOVERY_OUT','discovery/global/BE_EPROC_PAGINATOR'));OUT.mkdir(parents=True,exist_ok=True)
URL='https://www.publicprocurement.be/bda'
SEARCH_API='https://www.publicprocurement.be/api/sea/search/publications'

def main():
    chrome=os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome: raise SystemExit('no chrome')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox'])
        ctx=browser.new_context(locale='en-GB');page=ctx.new_page();calls=[]
        def req(r):
            if r.url.startswith(SEARCH_API):
                try: payload=json.loads(r.post_data or '{}')
                except Exception: payload={}
                calls.append({'method':r.method,'payload':payload})
        page.on('request',req)
        page.goto(URL,wait_until='domcontentloaded',timeout=60000)
        try: page.wait_for_load_state('networkidle',timeout=18000)
        except Exception: page.wait_for_timeout(5000)
        page.wait_for_timeout(1500)
        selectors='button,a,[role="button"],[role="link"],mat-paginator,.mat-paginator,.mat-mdc-paginator,[class*="pagin"],[class*="next"],[class*="arrow"],[class*="chevron"],[aria-label],[title]'
        nodes=page.locator(selectors).evaluate_all('''els => els.map((e,i)=>({
          i,tag:e.tagName,text:(e.innerText||e.textContent||'').trim().slice(0,300),
          aria:e.getAttribute('aria-label'),title:e.getAttribute('title'),role:e.getAttribute('role'),
          cls:typeof e.className==='string'?e.className:String(e.className||''),
          href:e.href||null,disabled:!!e.disabled,outer:e.outerHTML.slice(0,1200)
        }))''')
        html=page.content()
        snippets=[]
        for pat in ('paginator','next','chevron','arrow','page-size','pageIndex','pagination'):
            for m in list(re.finditer(pat,html,re.I))[:20]:
                snippets.append({'pattern':pat,'html':html[max(0,m.start()-800):min(len(html),m.end()+1600)]})
        body=page.locator('body').inner_text(timeout=10000)
        data={'calls':calls[:20],'nodes':nodes[:800],'snippets':snippets[:120],'body_tail':body[-12000:]}
        (OUT/'paginator_probe.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print('CALLS',json.dumps(calls[:10],ensure_ascii=False,indent=2))
        print('NODES',json.dumps(nodes[:800],ensure_ascii=False,indent=2)[:600000])
        print('SNIPPETS',json.dumps(snippets[:100],ensure_ascii=False,indent=2)[:500000])
        print('BODY_TAIL',body[-12000:])
        browser.close()
if __name__=='__main__': main()
