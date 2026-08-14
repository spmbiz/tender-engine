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

def save_bytes(body, headers, default='DCE.bin'):
    disp = headers.get('content-disposition') or ''
    ctype = (headers.get('content-type') or '').lower()
    name = default
    m = re.search(r"filename\*?=(?:UTF-8'')?[\"']?([^\"';]+)", disp, re.I)
    if m:
        name = m.group(1)
    elif 'zip' in ctype:
        name = 'DCE.zip'
    elif 'pdf' in ctype:
        name = 'DCE.pdf'
    path = OUT / name
    path.write_bytes(body)
    result['files'].append({'name':path.name,'size':path.stat().st_size,'sha256':hashlib.sha256(body).hexdigest(),'content_type':ctype})

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        responses = []

        def on_response(resp):
            try:
                h = resp.headers
                ct = (h.get('content-type') or '').lower()
                cd = (h.get('content-disposition') or '').lower()
                if any(x in ct for x in ['zip','pdf','octet-stream']) or 'attachment' in cd:
                    responses.append(resp)
            except Exception:
                pass

        page.on('response', on_response)
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(1500)
        (OUT/'page.html').write_text(page.content(), encoding='utf-8')

        # Exact portal controls. They are visually hidden, so set checked state via DOM and dispatch events.
        for selector in [ANON, TERMS]:
            page.locator(selector).evaluate("el => { el.checked = true; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
        page.wait_for_timeout(500)

        downloaded = False
        errors = []

        try:
            with page.expect_download(timeout=12000) as info:
                page.locator(VALIDATE).click(force=True)
            dl = info.value
            path = OUT / (dl.suggested_filename or 'DCE.zip')
            dl.save_as(path)
            body = path.read_bytes()
            result['files'].append({'name':path.name,'size':path.stat().st_size,'sha256':hashlib.sha256(body).hexdigest()})
            downloaded = True
        except Exception as e:
            errors.append('download_event: '+str(e))

        if not downloaded:
            page.wait_for_timeout(3000)
            for resp in list(responses):
                try:
                    body = resp.body()
                    if body:
                        save_bytes(body, resp.headers)
                        downloaded = True
                        break
                except Exception as e:
                    errors.append('response_body: '+str(e))

        if not downloaded:
            try:
                for a in page.locator('a[href]').all():
                    href = a.get_attribute('href') or ''
                    text = (a.inner_text() or '').strip()
                    hay = (href+' '+text).lower()
                    if any(x in hay for x in ['download','telecharg','télécharg','.zip','.pdf','dce']):
                        target = href if href.startswith('http') else page.url.rsplit('/',1)[0]+'/'+href.lstrip('/')
                        r = context.request.get(target, timeout=30000)
                        ct = (r.headers.get('content-type') or '').lower()
                        cd = (r.headers.get('content-disposition') or '').lower()
                        body = r.body()
                        if r.ok and body and (any(x in ct for x in ['zip','pdf','octet-stream']) or 'attachment' in cd):
                            save_bytes(body, r.headers)
                            downloaded = True
                            break
            except Exception as e:
                errors.append('post_submit_link: '+str(e))

        if downloaded:
            result['status']='DOWNLOADED'
        else:
            result['status']='NO_DOWNLOAD'
            txt = page.locator('body').inner_text(timeout=5000)
            err_excerpt = ''
            if 'Erreur de saisie' in txt:
                err_excerpt = ' | FORM_VALIDATION_ERROR'
            result['blocker']=' | '.join(errors[-6:]) + err_excerpt
            page.screenshot(path=str(OUT/'page.png'),full_page=True)
            (OUT/'page_after.html').write_text(page.content(), encoding='utf-8')

        browser.close()
except Exception as e:
    result['status']='ERROR_RETRYABLE'
    result['blocker']=str(e)

(OUT/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(result,indent=2,ensure_ascii=False))
if result['status'] != 'DOWNLOADED':
    raise SystemExit(2)
