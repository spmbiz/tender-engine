from pathlib import Path
import json,re
from playwright.sync_api import sync_playwright

TARGETS={
 'EHRC': {'needle':'EHRC 2627-14','dn':'DN825727'},
 'OLDHAM': {'needle':'Intelligent Automation','dn':'DN825199'},
}
BASE='https://procontract.due-north.com/SupplierRegistration/GridViewOpportunities'
OUT=Path('procontract_store'); OUT.mkdir(exist_ok=True)
results=[]

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    c=b.new_context()
    page=c.new_page()
    for key,t in TARGETS.items():
        found=[]
        for n in range(1,9):
            url=f'{BASE}?page={n}&pageSize=100&sortDirection=Descending&sortString=ExpressionStartDate'
            try:
                page.goto(url,wait_until='domcontentloaded',timeout=60000)
                page.wait_for_timeout(1200)
                html=page.content(); text=page.locator('body').inner_text()
                if t['needle'].lower() in text.lower() or t['dn'].lower() in text.lower():
                    for a in page.locator('a[href]').all():
                        href=a.get_attribute('href') or ''
                        at=(a.inner_text() or '').strip()
                        if t['needle'].lower() in at.lower() or t['dn'].lower() in at.lower() or 'advert' in href.lower():
                            found.append({'text':at,'href':href})
                    break
            except Exception:
                continue
        d=OUT/key; d.mkdir(parents=True,exist_ok=True)
        (d/'grid_matches.json').write_text(json.dumps(found,indent=2,ensure_ascii=False),encoding='utf-8')
        advert=None
        # exact-ish title link first
        for x in found:
            if t['needle'].lower() in x['text'].lower() and 'advert' in x['href'].lower(): advert=x['href']; break
        if not advert:
            for x in found:
                if 'advert' in x['href'].lower(): advert=x['href']; break
        status='NOT_FOUND'; detail={}
        if advert:
            if advert.startswith('/'): advert='https://procontract.due-north.com'+advert
            try:
                page.goto(advert,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(1500)
                body=page.locator('body').inner_text()
                (d/'advert.html').write_text(page.content(),encoding='utf-8')
                (d/'advert.txt').write_text(body,encoding='utf-8')
                links=[]
                for a in page.locator('a[href]').all():
                    links.append({'text':(a.inner_text() or '').strip(),'href':a.get_attribute('href') or ''})
                (d/'links.json').write_text(json.dumps(links,indent=2,ensure_ascii=False),encoding='utf-8')
                login=any(s in body.lower() for s in ['login and register interest','sign in','log in','register interest'])
                noatt='no attachments' in body.lower()
                publicatt='public attachments' in body.lower() and not noatt
                status='AUTH_REQUIRED' if login else ('PUBLIC_ATTACHMENTS' if publicatt else 'ADVERT_OPEN')
                detail={'advert':advert,'login':login,'no_attachments':noatt,'public_attachments':publicatt}
            except Exception as e:
                status='ERROR'; detail={'advert':advert,'error':str(e)}
        results.append({'key':key,'status':status,**detail,'matches':found[:10]})
    b.close()

(OUT/'summary.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(results,indent=2,ensure_ascii=False))
