from pathlib import Path
import json, hashlib, re
from playwright.sync_api import sync_playwright

URL = 'https://pmp.b2g.etat.lu/index.php?id=544016&orgAcronyme=t5y&page=Entreprise.EntrepriseDemandeTelechargementDce'
OUT = Path('dce_store/514529-2026')
OUT.mkdir(parents=True, exist_ok=True)

result = {'notice_id':'514529-2026','url':URL,'status':'STARTED','files':[],'blocker':None}
ANON = '#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_choixAnonyme'
TERMS = '#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_accepterConditions'
VALIDATE = '#ctl0_CONTENU_PAGE_validateButton'
COMPLETE = '#ctl0_CONTENU_PAGE_EntrepriseDownloadDce_completeDownload'

def save_download(dl):
    path = OUT / (dl.suggested_filename or 'DCE.zip')
    dl.save_as(path)
    body = path.read_bytes()
    result['files'].append({'name': path.name, 'size': path.stat().st_size, 'sha256': hashlib.sha256(body).hexdigest()})

def save_response(resp, default='DCE.bin'):
    body = resp.body()
    headers = resp.headers
    disp = headers.get('content-disposition') or ''
    ctype = (headers.get('content-type') or '').lower()
    name = default
    m = re.search(r"filename\*?=(?:UTF-8'')?[\"']?([^\"';]+)", disp, re.I)
    if m: name = m.group(1)
    elif 'zip' in ctype: name = 'DCE.zip'
    elif 'pdf' in ctype: name = 'DCE.pdf'
    path = OUT / name
    path.write_bytes(body)
    result['files'].append({'name': path.name, 'size': path.stat().st_size, 'sha256': hashlib.sha256(body).hexdigest(), 'content_type': ctype})

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        captured = []
        page.on('response', lambda r: captured.append(r) if any(x in ((r.headers.get('content-type') or '') + (r.headers.get('content-disposition') or '')).lower() for x in ['zip','pdf','octet-stream','attachment']) else None)
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(1200)

        for selector in [ANON, TERMS]:
            page.locator(selector).evaluate("el => { el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }")

        # Step 1: submit anonymous request. This normally navigates to the DCE download page.
        page.locator(VALIDATE).click(force=True)
        page.wait_for_load_state('domcontentloaded', timeout=30000)
        page.wait_for_timeout(1200)
        (OUT/'page_after_submit.html').write_text(page.content(), encoding='utf-8')

        downloaded = False
        errors = []

        # Step 2: click the actual Prado complete-download control on the resulting page.
        if page.locator(COMPLETE).count():
            try:
                with page.expect_download(timeout=20000) as info:
                    page.locator(COMPLETE).click(force=True)
                save_download(info.value)
                downloaded = True
            except Exception as e:
                errors.append('final_download_event: '+str(e))
                page.wait_for_timeout(1500)

        # Some Prado versions return attachment as a response rather than Playwright download event.
        if not downloaded:
            for resp in list(captured):
                try:
                    ct = (resp.headers.get('content-type') or '').lower()
                    cd = (resp.headers.get('content-disposition') or '').lower()
                    if any(x in ct for x in ['zip','pdf','octet-stream']) or 'attachment' in cd:
                        body = resp.body()
                        if body and len(body) > 1000:
                            save_response(resp)
                            downloaded = True
                            break
                except Exception as e:
                    errors.append('response_capture: '+str(e))

        if downloaded:
            result['status']='DOWNLOADED'
        else:
            result['status']='NO_DOWNLOAD'
            result['blocker']=' | '.join(errors[-6:]) or 'Final Prado download control did not yield attachment'
            page.screenshot(path=str(OUT/'page.png'), full_page=True)
            (OUT/'page_final.html').write_text(page.content(), encoding='utf-8')

        browser.close()
except Exception as e:
    result['status']='ERROR_RETRYABLE'
    result['blocker']=str(e)

(OUT/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(result,indent=2,ensure_ascii=False))
if result['status'] != 'DOWNLOADED':
    raise SystemExit(2)
